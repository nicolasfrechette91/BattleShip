@echo off
rem Index / browser for episode artifacts under runs\ (see replay\README.md).
rem   replay\replay_index scan ^| list [filters] ^| show N ^| play N ^| check N ^| gui
python "%~dp0replay_index.py" %*
exit /b %ERRORLEVEL%
