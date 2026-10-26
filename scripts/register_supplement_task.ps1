# 註冊 dsms 補抓的每日排程（增量 S，plan-supplement.md D11）。只需執行一次。
#
# 前置（只需一次）：在 repo 根目錄建立 venv 並安裝 requests
#     uv venv
#     uv pip install requests
#
# 每個參數都是修掉一個實際會咬人的預設值，別省：
# - -StartWhenAvailable：關機錯過的排程在下次開機補跑。這台不是全天開，少了它會靜默漏跑。
# - -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries：預設是筆電沒插電就整天不跑、
#   跑到一半拔電源就中斷。
# - -MultipleInstances IgnoreNew：防重入。兩個實例讀同一份前檔，較晚完成者會發布較舊的觀測。
# - -ExecutionTimeLimit 20 分鐘：正常約 3～5 分鐘（兩輪列表＋s3/s4 全部詳情），
#   含一次重試約 10 分鐘；卡住不該拖到預設的 72 小時。
# - 09:10：接在 recall-dashboard 的 09:00 之後，避免兩支同時對同一機關網站送請求。
#
# 註冊後務必核對，別信預設：
#     (Get-ScheduledTask -TaskName 'TFDA-shortage-supplement').Settings

$repo = Split-Path -Parent $PSScriptRoot
$a = New-ScheduledTaskAction -Execute "$repo\.venv\Scripts\pythonw.exe" `
       -Argument 'scripts\update_supplement.py' -WorkingDirectory $repo
$t = New-ScheduledTaskTrigger -Daily -At 09:10
$s = New-ScheduledTaskSettingsSet -StartWhenAvailable -RunOnlyIfNetworkAvailable `
       -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
       -MultipleInstances IgnoreNew `
       -ExecutionTimeLimit (New-TimeSpan -Minutes 20) `
       -RestartCount 2 -RestartInterval (New-TimeSpan -Minutes 15)
Register-ScheduledTask -TaskName 'TFDA-shortage-supplement' -Action $a -Trigger $t -Settings $s
