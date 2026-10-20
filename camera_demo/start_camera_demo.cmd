@echo off
python -X utf8 -B "%~dp0app.py" --backend software --self-test %*
