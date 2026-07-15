$ErrorActionPreference = "Stop"
Set-Location "D:\Sem8\stockbench-main\tradesys_dynamic_team\exercise"
$env:OPENAI_MAX_RETRIES = "3"
$tickers = @("AMZN", "MSFT", "NFLX", "TSLA")
$outRoot = "D:\Sem8\stockbench-main\tradesys_dynamic_team\exercise\analysis_results\full_llmcompiler_agent_eval_retry"
foreach ($ticker in $tickers) {
  $tickerOut = Join-Path $outRoot $ticker
  Write-Output "=== START $ticker $(Get-Date -Format o) ==="
  python run_analysis.py --ticker $ticker --start-date 2022-10-06 --end-date 2023-04-10 --workflow-mode llmcompiler --max-position-pct 25 --workers 2 --batch-size 8 --results-dir $tickerOut
  Write-Output "=== END $ticker $(Get-Date -Format o) exit=$LASTEXITCODE ==="
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
