# Verifies the two regexes INSIDE the real detect-test-procs.ps1 by reading
# them out of that file (not retyping them, which would test a copy).
# ASCII only.

$real = $args[0]
$text = Get-Content -Raw -Encoding UTF8 $real

# Measured 2026-11-02 on a CRLF copy: the extraction does NOT silently pick up
# a \r -- it fails outright with "cannot find $pattern" and exit 1, because in
# multiline mode $ matches before \n, and under CRLF the char before \n is \r,
# not the closing quote. So the failure is loud, which is the good outcome.
# .gitattributes pins *.ps1 to LF so it does not happen at all; .Trim() below
# is defensive only (it is not what saves us).
if ($text -notmatch "(?m)^\`$pattern = '(.+)'$") { Write-Host 'FAIL: cannot find $pattern'; exit 1 }
$pattern = $Matches[1].Trim()
if ($text -notmatch "(?m)^\`$excludePattern = '(.+)'$") { Write-Host 'FAIL: cannot find $excludePattern'; exit 1 }
$excludePattern = $Matches[1].Trim()

Write-Host ("pattern        = " + $pattern)
Write-Host ("excludePattern = " + $excludePattern)
Write-Host ''

# Both must be VALID regexes. An invalid one throws inside Where-Object,
# the script exits 1, the caller fails open -- detection silently never runs.
foreach ($p in @(@('pattern', $pattern), @('excludePattern', $excludePattern))) {
    try { [void][regex]::new($p[1]); Write-Host ("VALID REGEX: " + $p[0]) }
    catch { Write-Host ("INVALID REGEX: " + $p[0] + " -- " + $_.Exception.Message); exit 1 }
}
Write-Host ''

$cases = @(
    @{ n = 'pylance stub (expect EXCLUDED)';   c = 'c:\Python312\python.exe -B -I c:\Users\x\.vscode\extensions\ms-python.vscode-pylance-2026.4.1\dist\bundled\stubs\pytest\__init__.pyi' },
    @{ n = 'vscode-server (expect EXCLUDED)';  c = '/home/x/.vscode-server/extensions/foo/pytest_stub.py' },
    @{ n = 'real pytest (expect DETECT)';      c = 'C:\Users\x\TBMS_git\EDMS\backend\.venv\Scripts\python.exe -m pytest -n auto' },
    @{ n = 'xdist worker (expect DETECT)';     c = 'C:\Users\x\TBMS_git\worktrees\foo\backend\.venv\Scripts\python.exe -c import sys;exec(eval(sys.stdin.readline()))' },
    @{ n = 'vitest (expect DETECT)';           c = 'C:\Program Files\nodejs\node.exe C:\Users\x\TBMS_git\EDMS\frontend\node_modules\vitest\vitest.mjs run' },
    @{ n = 'playwright (expect DETECT)';       c = 'node C:\Users\x\TBMS_git\EDMS\e2e\node_modules\playwright\cli.js test' },
    @{ n = 'unrelated python (expect none)';   c = 'C:\Python312\python.exe manage.py runserver' }
)

$bad = 0
foreach ($t in $cases) {
    $hit = $t.c -match $pattern
    $ex = $t.c -match $excludePattern
    if ($hit -and -not $ex) { $res = 'DETECT' } elseif ($hit -and $ex) { $res = 'EXCLUDED' } else { $res = 'none' }
    $want = if ($t.n -match 'EXCLUDED') { 'EXCLUDED' } elseif ($t.n -match 'DETECT') { 'DETECT' } else { 'none' }
    $ok = if ($res -eq $want) { 'ok ' } else { $bad++; 'BAD' }
    Write-Host ("{0} {1,-34} -> {2}" -f $ok, $t.n, $res)
}
Write-Host ''
if ($bad -gt 0) { Write-Host ("FAILED: " + $bad + " case(s)"); exit 1 }
Write-Host 'ALL CASES OK'
