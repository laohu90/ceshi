@echo off
:: 设置窗口尺寸：cols=列数（宽度），lines=行数（高度），可自行修改数值
mode con cols=40 lines=25
:loop
php ./check_balance.php
ping -n 2 127.0.0.1>nul
cls
goto loop