/*
 * rl_transport.cpp -- M1d: single-client loopback TCP transport for the M1c
 * stepping primitive.
 *
 * WHAT IT IS. One listening socket on 127.0.0.1:SSB64_RL_PORT, one worker
 * thread, one client at a time, one request at a time. Requests and
 * responses are single-line JSON objects terminated by '\n'; every message
 * carries "protocol": RL_PROTOCOL_VERSION. The transport is plumbing only:
 * it maps three operations onto the existing M1c API and serialises
 * RLStepResult / RLObservation field-for-field. It never derives, rewrites
 * or normalises a native field, never touches game memory and never advances
 * the game by itself.
 *
 * WHY THIS TRANSPORT. The parent repository has no Windows-usable socket
 * facility (decomp/src/sys/netpeer.c is a POSIX-only debug UDP peer) and
 * libultraship has no IPC wrapper, so the smallest external-process,
 * Windows + Linux, dependency-free mechanism is a loopback TCP socket driven
 * from Python's standard library. nlohmann/json.hpp is already compiled into
 * the port (port/enhancements/Updater.cpp), so JSON costs no new dependency.
 * Shared memory, HTTP, WebSocket and RPC frameworks were deliberately not
 * chosen for M1d; see docs/rl_transport_m1d.md.
 *
 * PROTOCOL 1.
 *   -> {"protocol":1,"op":"ping"}
 *   <- {"protocol":1,"op":"ping","ok":true}
 *
 *   -> {"protocol":1,"op":"status"}
 *   <- {"protocol":1,"op":"status","ok":true,"state":2,
 *       "state_name":"WaitingForAction","can_step":true,"step_count":N,
 *       "no_render":bool}
 *      Non-consuming: it reads rlStepGetState() only and never calls
 *      rlStepPoll(), so it can never collect an ObservationReady result. It
 *      carries no observation on purpose: the only observation this
 *      transport forwards is the paired RLStepResult of a step, so the worker
 *      consumes M1c results only and never reads the M1b cache. step_count
 *      is the value of the last result this worker collected, which equals
 *      M1c's counter because the worker is the sole submitter and collector.
 *      no_render (M6, additive) is the process's constant host mode
 *      (SSB64_RL_NO_RENDER effective or not): configuration, not an
 *      observation, and a client may ignore it.
 *
 *   -> {"protocol":1,"op":"step","buttons":B,"stick_x":X,"stick_y":Y}
 *      B: JSON integer 0..65535 (the RL_BUTTON_* word), X / Y: JSON integer
 *      -128..127. Floats (even 3.0), booleans, strings and null are rejected
 *      before anything native is called; the button rule itself is
 *      rlStepSubmit's (rlStepValidateAction).
 *   <- {"protocol":1,"op":"step","ok":true,"step_schema":1,"state":S,
 *       "state_name":"...","step_count":N,"consumed_tick":T,
 *       "observation":{...}}
 *      The RLStepResult verbatim: observation.input_tick == T + 1.
 *
 *   -> {"protocol":1,"op":"observe"}
 *   <- {"protocol":1,"op":"observe","ok":true,"state":S,"state_name":"...",
 *       "can_step":bool,"step_count":N,"observation":{...}}
 *      M3 addition, additive to protocol 1 (ping / status / step are
 *      unchanged). Non-consuming by construction: it reads rlStepGetState()
 *      and rlStepGetLatestObservation(), both pure queries under the M1c
 *      mutex; it never calls rlStepPoll() or rlStepSubmit(), so it cannot
 *      collect a result, open the host gate or advance any clock. The
 *      observation is the newest M1b snapshot the state machine holds: in
 *      WaitingForAction the state the next action will act upon (at
 *      step_count 0, the state before native tick 0, input_tick == 0), in
 *      EpisodeEnded the terminal snapshot. Exists so a Gymnasium reset() can
 *      return the initial observation without consuming tick 0. Fails with
 *      the protocol error no_observation (native_code null) only before the
 *      first GamePostUpdateEvent has captured anything.
 *
 *   <- {"protocol":1,"op":<op or null>,"ok":false,"error":"<name>",
 *       "message":"...","native_code":<int>|null}
 *      Protocol errors (native_code null): malformed_request,
 *      unsupported_protocol, unknown_op, missing_field, out_of_range,
 *      no_observation.
 *      Native errors carry the RL_STEP_ERR_* code verbatim plus its name:
 *      null(-1), disabled(-2), invalid_action(-3), not_ready(-4), busy(-5),
 *      episode_ended(-6), stopping(-7), main_thread(-8).
 *      No error response ever advances the game.
 *
 *   M4 diagnostic, only with SSB64_RL_TIMING=1: a successful step response
 *   additionally carries "timing":{"timing_schema":1,"clock":
 *   "steady_clock_ns_differences_only","request_received_ns":..,"submit_ns":..,
 *   "gate_open_ns":..,"consumed_ns":..,"logic_done_ns":..,"observation_ns":..,
 *   "collected_ns":..,"response_ready_ns":..,"host_iterations":N,
 *   "parked_iterations":N}. Additive: the key is absent (never null) when
 *   the diagnostic is off, nothing inside "observation" changes, and the
 *   protocol version stays 1. Stamps are ns readings of the game's steady
 *   clock; only differences are meaningful; 0 = not taken. request_received
 *   is taken when the worker extracts the request line from its buffer (a
 *   pipelined line is stamped when reached, not on arrival); response_ready
 *   is taken before the JSON dump and send.
 *
 * THREADING.
 *   Python -> worker thread -> rlStepSubmit() / rlStepWait()
 *          -> main-thread host gate -> one native input tick
 *          -> M1b observation -> rlStepWait() returns -> worker -> Python
 * The worker holds no lock while calling the M1c API; rl_step.cpp's own
 * mutex / condition variable is the only game-facing synchronisation and
 * rlStepWait() blocks on it without polling. The one mutex in this file
 * guards the two socket handles for the shutdown path and nothing else.
 *
 * DISCONNECT. A disconnect never touches the state machine.
 *   - While WaitingForAction: the game stays parked (gate closed) until the
 *     next client steps; the window keeps pumping events and presenting.
 *   - After a step was submitted but before its response was read: the
 *     worker still collects the paired result through rlStepWait() and
 *     answers; the reply is either discarded by the closed peer or fails to
 *     send (the latter is logged). The state machine has already moved on
 *     (WaitingForAction or EpisodeEnded), so the next client's status shows
 *     step_count and observation.input_tick advanced by exactly that one
 *     step. The action was consumed exactly once.
 *   - ObservationReady is never visible from outside: the worker is the only
 *     collector and collects inside the same request.
 *   A second connection while one is active waits in the listen backlog and
 *   is served once the active client disconnects.
 *
 * SHUTDOWN. main() calls rlRuntimeShutdown() first, which wakes a worker
 * blocked in rlStepWait() with RL_STEP_ERR_STOPPING (the client receives a
 * "stopping" error or an EOF), then rlTransportShutdown(): stop flag,
 * shutdown() of the listening socket, join, WSACleanup. Every blocking socket
 * wait in the worker is a select() with a short timeout that re-checks the
 * stop flag, so the join is bounded.
 *
 * Out of scope by design: reset, restart, rewards, save states, headless,
 * shared memory, multiple clients, Track 1 discretisation, RNG.
 */
#include "rl/rl.h"

#include "port_log.h"

#include <nlohmann/json.hpp>

#ifdef _WIN32
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <winsock2.h>
#include <ws2tcpip.h>
#else
#include <errno.h>
#include <netinet/in.h>
#include <sys/select.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <unistd.h>
#endif

#include <atomic>
#include <chrono>
#include <cstdint>
#include <cstring>
#include <mutex>
#include <string>
#include <thread>

namespace {

using json = nlohmann::json;

#ifdef _WIN32
typedef SOCKET Socket;
const Socket kInvalidSocket = INVALID_SOCKET;
#else
typedef int Socket;
const Socket kInvalidSocket = -1;
#endif

const size_t kMaxLineBytes = 8192;    /* a request is a few dozen bytes */
const long kSelectTimeoutUs = 250000; /* stop-flag re-check period for blocking socket waits */

std::thread sWorker;
std::atomic<bool> sStarted{false};
std::atomic<bool> sStop{false};

std::mutex sSocketMutex; /* guards sListen / sClient handles only */
Socket sListen = kInvalidSocket;
Socket sClient = kInvalidSocket;

/* --- worker thread only ---------------------------------------------------- */
uint32_t sConnections = 0;
uint32_t sLastStepCount = 0; /* step_count of the last RLStepResult collected by this worker */

/* M4 timing diagnostic (SSB64_RL_TIMING=1). sTimingEnabled is written once by
 * rlTransportStart() before the worker exists; sRequestReceivedNs is set by
 * serveClient() for the request being handled and read by handleStep(). */
bool sTimingEnabled = false;
uint64_t sRequestReceivedNs = 0;

uint64_t nowNs() {
	return (uint64_t)std::chrono::duration_cast<std::chrono::nanoseconds>(
	           std::chrono::steady_clock::now().time_since_epoch())
	    .count();
}

int lastSocketError() {
#ifdef _WIN32
	return WSAGetLastError();
#else
	return errno;
#endif
}

void closeSocket(Socket s) {
#ifdef _WIN32
	closesocket(s);
#else
	close(s);
#endif
}

void shutdownSocket(Socket s) {
#ifdef _WIN32
	shutdown(s, SD_BOTH);
#else
	shutdown(s, SHUT_RDWR);
#endif
}

/* Block until s is readable (data, EOF or a pending connection). Returns
 * false once stop has been requested or select() fails. */
bool waitReadable(Socket s) {
	for (;;) {
		if (sStop.load()) {
			return false;
		}
		fd_set readSet;
		FD_ZERO(&readSet);
		FD_SET(s, &readSet);
		timeval tv;
		tv.tv_sec = 0;
		tv.tv_usec = kSelectTimeoutUs;
#ifdef _WIN32
		const int nfds = 0; /* ignored by Winsock */
#else
		const int nfds = s + 1;
#endif
		const int r = select(nfds, &readSet, nullptr, nullptr, &tv);
		if (r > 0) {
			return true;
		}
		if (r < 0) {
			const int err = lastSocketError();
#ifdef _WIN32
			if (err == WSAEINTR) {
				continue;
			}
#else
			if (err == EINTR) {
				continue;
			}
#endif
			return false;
		}
	}
}

bool sendAll(Socket s, const std::string &data) {
	size_t off = 0;
	while (off < data.size()) {
		const int n = (int)send(s, data.data() + off, (int)(data.size() - off), 0);
		if (n <= 0) {
			return false;
		}
		off += (size_t)n;
	}
	return true;
}

const char *stateName(uint32_t s) {
	switch ((RLStepState)s) {
	case RL_STEP_DISABLED:
		return "Disabled";
	case RL_STEP_INACTIVE:
		return "Inactive";
	case RL_STEP_WAITING_FOR_ACTION:
		return "WaitingForAction";
	case RL_STEP_ACTION_READY:
		return "ActionReady";
	case RL_STEP_ACTION_CONSUMED:
		return "ActionConsumed";
	case RL_STEP_OBSERVATION_READY:
		return "ObservationReady";
	case RL_STEP_EPISODE_ENDED:
		return "EpisodeEnded";
	case RL_STEP_STOPPING:
		return "Stopping";
	default:
		return "?";
	}
}

const char *nativeErrorName(int code) {
	switch (code) {
	case RL_STEP_ERR_NULL:
		return "null";
	case RL_STEP_ERR_DISABLED:
		return "disabled";
	case RL_STEP_ERR_INVALID_ACTION:
		return "invalid_action";
	case RL_STEP_ERR_NOT_READY:
		return "not_ready";
	case RL_STEP_ERR_BUSY:
		return "busy";
	case RL_STEP_ERR_EPISODE_ENDED:
		return "episode_ended";
	case RL_STEP_ERR_STOPPING:
		return "stopping";
	case RL_STEP_ERR_MAIN_THREAD:
		return "main_thread";
	default:
		return "native_error";
	}
}

/* RLObservation, field for field, in declaration order. Integers stay JSON
 * integers; the five floats are emitted as JSON numbers carrying the exact
 * float value (widened to double, the value itself is not rounded). */
json observationToJson(const RLObservation &o) {
	json j;
	j["observation_schema"] = o.observation_schema;
	j["host_frame"] = o.host_frame;
	j["input_tick"] = o.input_tick;
	j["time_passed"] = o.time_passed;
	j["game_status"] = o.game_status;
	j["btt_active"] = o.btt_active;
	j["targets_remaining"] = o.targets_remaining;
	j["fighter_valid"] = o.fighter_valid;
	j["position_x"] = o.position_x;
	j["position_y"] = o.position_y;
	j["air_velocity_x"] = o.air_velocity_x;
	j["air_velocity_y"] = o.air_velocity_y;
	j["ground_velocity_x"] = o.ground_velocity_x;
	j["facing_direction"] = o.facing_direction;
	j["ground_air_state"] = o.ground_air_state;
	j["fighter_status_id"] = o.fighter_status_id;
	j["jumps_used"] = o.jumps_used;
	return j;
}

json baseResponse(const json &op) {
	json r;
	r["protocol"] = RL_PROTOCOL_VERSION;
	r["op"] = op.is_string() ? op : json(nullptr);
	return r;
}

json protocolError(const json &op, const char *error, const std::string &message) {
	json r = baseResponse(op);
	r["ok"] = false;
	r["error"] = error;
	r["message"] = message;
	r["native_code"] = nullptr;
	return r;
}

json nativeError(const json &op, int code, const std::string &message) {
	json r = baseResponse(op);
	r["ok"] = false;
	r["error"] = nativeErrorName(code);
	r["message"] = message;
	r["native_code"] = code;
	return r;
}

/* Accept only a JSON integer within [lo, hi]. Floats (even 3.0), booleans,
 * strings and null are rejected: nothing is coerced before the native call. */
bool readInteger(const json &req, const json &op, const char *key, long long lo, long long hi, long long *out,
                 json *err) {
	const std::string range = std::string(key) + " must be in [" + std::to_string(lo) + ", " + std::to_string(hi) + "]";
	if (!req.contains(key) || req[key].is_null()) {
		*err = protocolError(op, "missing_field", std::string(key) + " is required");
		return false;
	}
	const json &v = req[key];
	if (!v.is_number_integer()) {
		*err = protocolError(op, "malformed_request", std::string(key) + " must be a JSON integer");
		return false;
	}
	if (v.is_number_unsigned()) {
		const uint64_t u = v.get<uint64_t>();
		if (u > (uint64_t)hi) {
			*err = protocolError(op, "out_of_range", range);
			return false;
		}
		*out = (long long)u;
	} else {
		*out = v.get<long long>();
	}
	if (*out < lo || *out > hi) {
		*err = protocolError(op, "out_of_range", range);
		return false;
	}
	return true;
}

/* Non-consuming by construction: rlStepGetState() is a pure query under the
 * M1c mutex. rlStepPoll() is deliberately NOT used here because it collects
 * an ObservationReady result; only a step request may submit and collect.
 * No observation is returned: the worker never reads the M1b cache, and the
 * only observation it forwards is the paired RLStepResult of a step. */
json handleStatus(const json &op) {
	const uint32_t state = (uint32_t)rlStepGetState();
	json r = baseResponse(op);
	r["ok"] = true;
	r["state"] = state;
	r["state_name"] = stateName(state);
	r["can_step"] = (state == RL_STEP_WAITING_FOR_ACTION);
	r["step_count"] = sLastStepCount;
	/* M6: additive, constant per process; lets a client prove which host
	 * mode the process it is stepping actually runs in. */
	r["no_render"] = rlNoRenderIsEnabled() != 0;
	return r;
}

/* M3: the status metadata plus a copy of the newest M1b snapshot held by the
 * M1c state machine. Both calls are pure queries (rlStepGetState,
 * rlStepGetLatestObservation); rlStepPoll() is still never used here, so
 * this op can neither collect a result nor advance the game. */
json handleObserve(const json &op) {
	RLObservation observation;
	std::memset(&observation, 0, sizeof(observation));
	const int have = rlStepGetLatestObservation(&observation);
	const uint32_t state = (uint32_t)rlStepGetState();
	if (!have) {
		return protocolError(op, "no_observation",
		                     std::string("no observation has been captured yet (state ") + stateName(state) + ")");
	}
	json r = baseResponse(op);
	r["ok"] = true;
	r["state"] = state;
	r["state_name"] = stateName(state);
	r["can_step"] = (state == RL_STEP_WAITING_FOR_ACTION);
	r["step_count"] = sLastStepCount;
	r["observation"] = observationToJson(observation);
	return r;
}

json handleStep(const json &req, const json &op) {
	long long buttons = 0;
	long long stickX = 0;
	long long stickY = 0;
	json err;
	if (!readInteger(req, op, "buttons", 0, 0xFFFF, &buttons, &err) ||
	    !readInteger(req, op, "stick_x", -128, 127, &stickX, &err) ||
	    !readInteger(req, op, "stick_y", -128, 127, &stickY, &err)) {
		return err;
	}

	RLAction action;
	action.buttons = (uint16_t)buttons;
	action.stick_x = (int8_t)stickX;
	action.stick_y = (int8_t)stickY;

	int rc = rlStepSubmit(&action);
	if (rc != RL_STEP_OK) {
		return nativeError(op, rc, "rlStepSubmit rejected the request; nothing advanced");
	}

	/* Blocks on M1c's condition variable until the main thread has run the
	 * one native tick and captured its observation. No polling. */
	RLStepResult result;
	rc = rlStepWait(&result);
	if (rc != RL_STEP_OK) {
		/* Reachable only when shutdown began while the action was in flight
		 * (RL_STEP_ERR_STOPPING); the paired result no longer exists. */
		return nativeError(op, rc,
		                   "action accepted but rlStepWait returned code " + std::to_string(rc) +
		                       " before a paired result was produced");
	}
	sLastStepCount = result.step_count;

	json r = baseResponse(op);
	r["ok"] = true;
	r["step_schema"] = result.step_schema;
	r["state"] = result.state;
	r["state_name"] = stateName(result.state);
	r["step_count"] = result.step_count;
	r["consumed_tick"] = result.consumed_tick;
	r["observation"] = observationToJson(result.observation);

	if (sTimingEnabled) {
		/* M4: attach the game's own stamps for exactly this step. Additive
		 * key; absent whenever the diagnostic is off or the stamps do not
		 * belong to this step_count. */
		RLStepTiming t;
		std::memset(&t, 0, sizeof(t));
		if (rlStepGetLastTiming(&t) && t.step_count == result.step_count) {
			json tj;
			tj["timing_schema"] = t.timing_schema;
			tj["clock"] = "steady_clock_ns_differences_only";
			tj["request_received_ns"] = sRequestReceivedNs;
			tj["submit_ns"] = t.submit_ns;
			tj["gate_open_ns"] = t.gate_open_ns;
			tj["consumed_ns"] = t.consumed_ns;
			tj["logic_done_ns"] = t.logic_done_ns;
			tj["observation_ns"] = t.observation_ns;
			tj["collected_ns"] = t.collected_ns;
			tj["response_ready_ns"] = nowNs();
			tj["host_iterations"] = t.host_iterations;
			tj["parked_iterations"] = t.parked_iterations;
			r["timing"] = tj;
		}
	}
	return r;
}

json handleLine(const std::string &line) {
	const json req = json::parse(line, nullptr, false);
	if (req.is_discarded() || !req.is_object()) {
		return protocolError(json(nullptr), "malformed_request", "each request must be one JSON object per line");
	}
	const json op = req.contains("op") ? req["op"] : json(nullptr);

	if (!req.contains("protocol") || !req["protocol"].is_number_integer() ||
	    req["protocol"].get<long long>() != (long long)RL_PROTOCOL_VERSION) {
		return protocolError(op, "unsupported_protocol",
		                     "this server speaks protocol " + std::to_string(RL_PROTOCOL_VERSION) + " only");
	}
	if (!op.is_string()) {
		return protocolError(json(nullptr), "malformed_request", "op must be a string");
	}
	const std::string name = op.get<std::string>();
	if (name == "ping") {
		json r = baseResponse(op);
		r["ok"] = true;
		return r;
	}
	if (name == "status") {
		return handleStatus(op);
	}
	if (name == "step") {
		return handleStep(req, op);
	}
	if (name == "observe") {
		return handleObserve(op);
	}
	return protocolError(op, "unknown_op", "unknown op '" + name + "'; expected ping, status, step or observe");
}

void serveClient(Socket c) {
	std::string buffer;
	char chunk[4096];
	for (;;) {
		size_t nl;
		while ((nl = buffer.find('\n')) != std::string::npos) {
			std::string line = buffer.substr(0, nl);
			buffer.erase(0, nl + 1);
			if (!line.empty() && line.back() == '\r') {
				line.pop_back();
			}
			if (line.empty()) {
				continue;
			}
			if (sTimingEnabled) {
				sRequestReceivedNs = nowNs(); /* M4: request line in hand, not yet parsed */
			}
			const json response = handleLine(line);
			if (!sendAll(c, response.dump() + "\n")) {
				const json &opj = response.at("op");
				if (response.at("ok").get<bool>() && opj.is_string() && opj.get<std::string>() == "step") {
					port_log("SSB64 RL Transport: client left before reading the result for consumed_tick=%u "
					         "(input_tick=%u step_count=%u); it was collected and the next status reflects it\n",
					         response.at("consumed_tick").get<uint32_t>(),
					         response.at("observation").at("input_tick").get<uint32_t>(),
					         response.at("step_count").get<uint32_t>());
				}
				return;
			}
		}
		if (buffer.size() > kMaxLineBytes) {
			sendAll(c, protocolError(json(nullptr), "malformed_request", "request line exceeds 8192 bytes").dump() +
			               "\n");
			return;
		}
		if (!waitReadable(c)) {
			return;
		}
		const int n = (int)recv(c, chunk, (int)sizeof(chunk), 0);
		if (n <= 0) {
			return; /* EOF or error */
		}
		buffer.append(chunk, (size_t)n);
	}
}

void workerMain() {
	for (;;) {
		Socket listenSock;
		{
			std::lock_guard<std::mutex> lock(sSocketMutex);
			listenSock = sListen;
		}
		if (listenSock == kInvalidSocket || !waitReadable(listenSock)) {
			break;
		}
		sockaddr_in peer;
		socklen_t peerLen = sizeof(peer);
		const Socket c = accept(listenSock, (sockaddr *)&peer, &peerLen);
		if (c == kInvalidSocket) {
			if (sStop.load()) {
				break;
			}
			port_log("SSB64 RL Transport: accept failed error=%d\n", lastSocketError());
			continue;
		}
		{
			std::lock_guard<std::mutex> lock(sSocketMutex);
			sClient = c;
		}
		sConnections++;
		port_log("SSB64 RL Transport: client %u connected state=%s\n", sConnections,
		         stateName((uint32_t)rlStepGetState()));

		serveClient(c);

		{
			std::lock_guard<std::mutex> lock(sSocketMutex);
			shutdownSocket(c);
			closeSocket(c);
			sClient = kInvalidSocket;
		}
		port_log("SSB64 RL Transport: client %u disconnected state=%s steps=%u\n", sConnections,
		         stateName((uint32_t)rlStepGetState()), sLastStepCount);
	}
	{
		std::lock_guard<std::mutex> lock(sSocketMutex);
		if (sListen != kInvalidSocket) {
			closeSocket(sListen);
			sListen = kInvalidSocket;
		}
	}
	port_log("SSB64 RL Transport: worker exited\n");
}

} // namespace

extern "C" void rlTransportStart(void) {
	const int port = rlTransportPort();
	if (port <= 0 || !rlStepIsEnabled() || sStarted.load()) {
		return;
	}

#ifdef _WIN32
	WSADATA wsa;
	const int wsaErr = WSAStartup(MAKEWORD(2, 2), &wsa);
	if (wsaErr != 0) {
		port_log("SSB64 RL Transport: ERROR: WSAStartup failed error=%d; transport disabled\n", wsaErr);
		return;
	}
#endif

	/* Bound on the main thread so a failure is reported synchronously, in
	 * order, before the first frame. */
	const Socket s = socket(AF_INET, SOCK_STREAM, 0);
	if (s == kInvalidSocket) {
		port_log("SSB64 RL Transport: ERROR: socket failed error=%d; transport disabled\n", lastSocketError());
#ifdef _WIN32
		WSACleanup();
#endif
		return;
	}
#ifndef _WIN32
	/* Allow an immediate rebind after a previous run left the port in
	 * TIME_WAIT. Not set on Windows, where SO_REUSEADDR would let another
	 * process bind the same port. */
	int one = 1;
	setsockopt(s, SOL_SOCKET, SO_REUSEADDR, &one, sizeof(one));
#endif
	sockaddr_in addr;
	std::memset(&addr, 0, sizeof(addr));
	addr.sin_family = AF_INET;
	addr.sin_port = htons((uint16_t)port);
	addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK); /* loopback only, never 0.0.0.0 */
	if (bind(s, (const sockaddr *)&addr, sizeof(addr)) != 0) {
		port_log("SSB64 RL Transport: ERROR: bind 127.0.0.1:%d failed error=%d; transport disabled\n", port,
		         lastSocketError());
		closeSocket(s);
#ifdef _WIN32
		WSACleanup();
#endif
		return;
	}
	if (listen(s, 1) != 0) {
		port_log("SSB64 RL Transport: ERROR: listen failed error=%d; transport disabled\n", lastSocketError());
		closeSocket(s);
#ifdef _WIN32
		WSACleanup();
#endif
		return;
	}
	{
		std::lock_guard<std::mutex> lock(sSocketMutex);
		sListen = s;
	}
	sStop.store(false);
	sTimingEnabled = rlTimingIsEnabled() != 0; /* M4 diagnostic, opt-in; read before the worker exists */
	sStarted.store(true);
	port_log("SSB64 RL Transport: listening on 127.0.0.1:%d protocol=%u (one client, one request at a time)%s\n",
	         port, (unsigned)RL_PROTOCOL_VERSION, sTimingEnabled ? " timing=1" : "");
	sWorker = std::thread(workerMain);
}

extern "C" void rlTransportShutdown(void) {
	if (!sStarted.load()) {
		return;
	}
	sStop.store(true);
	{
		/* The listening socket is shut down so a pending accept() fails at
		 * once where the platform supports it. The client socket is left to
		 * the worker, which notices the stop flag within one select period
		 * and delivers whatever response it was producing (typically the
		 * "stopping" error from rlStepWait) before closing, so the peer gets
		 * a clean EOF. */
		std::lock_guard<std::mutex> lock(sSocketMutex);
		if (sListen != kInvalidSocket) {
			shutdownSocket(sListen);
		}
	}
	if (sWorker.joinable()) {
		sWorker.join();
	}
#ifdef _WIN32
	WSACleanup();
#endif
	sStarted.store(false);
	port_log("SSB64 RL Transport: stopped connections=%u\n", sConnections);
}
