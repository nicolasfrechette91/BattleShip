@echo off
rem BattleShip episode replay viewer (see replay\README.md).
rem   replay\replay <episode dir | actions.jsonl> [--play] [--speed S] [--start-tick N] [--check] ...
python "%~dp0replay.py" %*
exit /b %ERRORLEVEL%
