@echo off
cd /d "%~dp0"
echo ============================================
echo  FM27 얼굴 교체 프로그램 - 설치
echo ============================================
set PY=
py -3.13 -c "1" >nul 2>nul && set PY=py -3.13
if not defined PY (py -3.12 -c "1" >nul 2>nul && set PY=py -3.12)
if not defined PY (where py >nul 2>nul && set PY=py -3)
if not defined PY (where python >nul 2>nul && set PY=python)
if not defined PY (
  echo [오류] 파이썬이 없습니다.
  echo https://www.python.org/downloads/ 에서 Python 3.12 또는 3.13을 설치하세요.
  echo 설치 첫 화면에서 "Add python.exe to PATH"를 꼭 체크하세요.
  pause
  exit /b 1
)
%PY% -c "import sys; sys.exit(0 if sys.version_info>=(3,10) else 1)" || (
  echo [오류] 파이썬 3.10 이상이 필요합니다.
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
  echo 가상환경 만드는 중...
  %PY% -m venv .venv || (echo [오류] 가상환경을 만들지 못했습니다. & pause & exit /b 1)
)
echo 필요한 부품 설치 중... (몇 분 걸릴 수 있어요)
".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
".venv\Scripts\python.exe" -m pip install -r requirements.txt || (echo [오류] 설치 실패 & pause & exit /b 1)
echo.
echo 설치 완료! 이제 "실행.bat"을 더블클릭하세요.
pause
