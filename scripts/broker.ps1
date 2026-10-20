param([ValidateSet('Start','Stop','Status')][string]$Action = 'Start')
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskRuntime = Join-Path $taskRoot '.runtime'
$taskVersion = '4.3.1'
$taskArchiveName = "kafka_2.13-$taskVersion.tgz"
$taskHome = Join-Path $taskRuntime "kafka_2.13-$taskVersion"
$taskPidFile = Join-Path $taskRuntime 'broker.pid'
function Get-TaskBroker {
    if (Test-Path -LiteralPath $taskPidFile) {
        $taskBrokerId = [int](Get-Content -LiteralPath $taskPidFile -Raw)
        $taskProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$taskBrokerId"
        if ($taskProcess -and $taskProcess.CommandLine -like "*kafka.Kafka*" -and $taskProcess.CommandLine -like "*$taskRuntime*") { return $taskProcess }
    }
    return $null
}
$taskExisting = Get-TaskBroker
if ($Action -eq 'Status') {
    if ($taskExisting) { Write-Output "Native Kafka PID $($taskExisting.ProcessId)" } else { Write-Output 'Native Kafka is stopped' }
    exit 0
}
if ($Action -eq 'Stop') {
    if ($taskExisting) { Stop-Process -Id $taskExisting.ProcessId; Write-Output 'Native Kafka stopped' }
    exit 0
}
if ($taskExisting) { Write-Output "Native Kafka already running: $($taskExisting.ProcessId)"; exit 0 }
if (Get-NetTCPConnection -LocalPort 19092 -State Listen -ErrorAction SilentlyContinue) { throw 'Port 19092 is occupied; do not start a second broker.' }
$taskJava = (Get-Command java -ErrorAction Stop).Source
New-Item -ItemType Directory -Path $taskRuntime -Force | Out-Null
if (-not (Test-Path -LiteralPath $taskHome)) {
    $taskArchive = Join-Path $taskRuntime $taskArchiveName
    $taskChecksum = Join-Path $taskRuntime 'kafka.sha512'
    if (-not (Test-Path -LiteralPath $taskArchive)) {
        Invoke-WebRequest -Uri "https://dlcdn.apache.org/kafka/$taskVersion/$taskArchiveName" -OutFile $taskArchive
    }
    if (-not (Test-Path -LiteralPath $taskChecksum)) {
        Invoke-WebRequest -Uri "https://dlcdn.apache.org/kafka/$taskVersion/$taskArchiveName.sha512" -OutFile $taskChecksum
    }
    $taskExpectedHash = ((Get-Content -LiteralPath $taskChecksum -Raw) -replace '^[^:]+:\s*','') -replace '\s',''
    $taskActualHash = (Get-FileHash -LiteralPath $taskArchive -Algorithm SHA512).Hash
    if ($taskExpectedHash -notmatch '^[A-Fa-f0-9]{128}$' -or $taskActualHash -ne $taskExpectedHash) { throw 'Kafka archive SHA512 verification failed' }
    & tar -xzf $taskArchive -C $taskRuntime
    if ($LASTEXITCODE -ne 0) { throw 'Kafka extraction failed' }
}
$taskData = (Join-Path $taskRuntime 'kafka-data').Replace('\','/')
$taskConfig = Join-Path $taskRuntime 'server.properties'
@"
process.roles=broker,controller
node.id=1
controller.quorum.voters=1@localhost:19093
controller.listener.names=CONTROLLER
listeners=PLAINTEXT://127.0.0.1:19092,CONTROLLER://127.0.0.1:19093
advertised.listeners=PLAINTEXT://localhost:19092
listener.security.protocol.map=CONTROLLER:PLAINTEXT,PLAINTEXT:PLAINTEXT
inter.broker.listener.name=PLAINTEXT
log.dirs=$taskData
num.partitions=4
offsets.topic.replication.factor=1
transaction.state.log.replication.factor=1
transaction.state.log.min.isr=1
group.initial.rebalance.delay.ms=0
"@ | Set-Content -LiteralPath $taskConfig -Encoding utf8
$taskClassPath = Join-Path $taskHome 'libs\*'
if (-not (Test-Path -LiteralPath (Join-Path $taskData 'meta.properties'))) {
    & $taskJava -cp $taskClassPath kafka.tools.StorageTool format -t 'MkU3OEVBNTcwNTJENDM2Qk' -c $taskConfig
    if ($LASTEXITCODE -ne 0) { throw 'Kafka storage formatting failed' }
}
$taskLogging = (Join-Path $taskHome 'config\log4j2.yaml').Replace('\','/')
$taskArguments = @('-Xms256m','-Xmx512m',"-Dlog4j.configurationFile=file:$taskLogging",'-cp',"`"$taskClassPath`"",'kafka.Kafka',"`"$taskConfig`"")
$taskBroker = Start-Process -FilePath $taskJava -ArgumentList $taskArguments -WorkingDirectory $taskRuntime -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $taskRuntime 'broker.stdout.log') -RedirectStandardError (Join-Path $taskRuntime 'broker.stderr.log')
$taskBroker.Id | Set-Content -LiteralPath $taskPidFile
for ($taskTry = 0; $taskTry -lt 30; $taskTry++) {
    if ($taskBroker.HasExited) { throw "Kafka exited. Read $taskRuntime/broker.stderr.log and broker.stdout.log" }
    if (Get-NetTCPConnection -LocalPort 19092 -State Listen -ErrorAction SilentlyContinue) { Write-Output "Native Kafka started: PID $($taskBroker.Id), localhost:19092"; exit 0 }
    Start-Sleep -Seconds 1
}
throw 'Kafka did not open port 19092 in 30 seconds; inspect .runtime broker logs'
