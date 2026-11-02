# ============================================================
# Detect concurrently running test processes (EDMS issue #635).
#
# Emits one TSV line per match:
#   <pid>\t<image>\t<cpu-percent>\t<worktree>\t<trimmed-command-line>
# No match -> no output, exit 0. Any failure -> exit 1 (caller fails open).
#
# ASCII ONLY. A UTF-8 file without BOM is read as ANSI by Windows
# PowerShell 5.1; non-ASCII here makes the whole script fail to parse and
# the detection silently never runs. All human-facing Chinese text lives in
# scripts/local-ci.sh instead.
# ============================================================

# Fingerprints. Keep in sync with _TEST_PROC_PATTERN in scripts/local-ci.sh
# (that file is the single source of truth; this is the PowerShell dialect).
$pattern = 'vitest|playwright|pytest|stdin\.readline'

# Editor/IDE tooling that merely *ships* those names (Pylance bundles pytest
# type stubs, so its command line matches). Observed 2026-11-02: a Pylance
# process showed up at 82% CPU in the warning, which is a false positive --
# and a warning that cries wolf gets ignored, including when it is real.
#
# Deliberately an exclusion, not a narrower $pattern: narrowing the fingerprint
# to one runner is how the "I grepped for execnet workers and missed a whole
# vitest run" hole gets reopened (see sti-testing.md step 0).
# [\\/] on both sides: local-ci.sh is a bash script and also runs under WSL,
# where these paths use forward slashes. A backslash-only rule silently
# misses .vscode-server there (caught by the pattern test, not by review).
$excludePattern = '[\\/]\.vscode[\\/]extensions[\\/]|[\\/]\.vscode-server[\\/]|[\\/]JetBrains[\\/]|[\\/]Microsoft VS Code[\\/]'

try {
    $self = $PID

    # Only node/python: a bare command-line match would also hit the shell
    # that launched this query (its argv contains the pattern above).
    $procs = @(Get-CimInstance Win32_Process -ErrorAction Stop |
        Where-Object {
            $_.Name -match '^(node|python)(\.exe)?$' -and
            $_.ProcessId -ne $self -and
            $_.CommandLine -and
            $_.CommandLine -match $pattern -and
            $_.CommandLine -notmatch $excludePattern
        })

    if ($procs.Count -eq 0) { exit 0 }

    # Current CPU usage, NOT Get-Process | Sort-Object CPU (that is cumulative
    # seconds since start, i.e. "has been open a long time", not "busy now").
    # _Total and Idle must be excluded or the sum exceeds 100 * cores.
    $perf = @{}
    Get-CimInstance Win32_PerfFormattedData_PerfProc_Process -ErrorAction Stop |
        Where-Object { $_.Name -ne '_Total' -and $_.Name -ne 'Idle' } |
        ForEach-Object { $perf[[int]$_.IDProcess] = [int]$_.PercentProcessorTime }

    $cores = [Environment]::ProcessorCount

    foreach ($p in $procs) {
        $cmd = $p.CommandLine

        # Worktree name: the venv/node interpreter path carries it, so this
        # works for xdist workers too (their own argv is just stdin.readline).
        if ($cmd -match 'worktrees[\\/]([^\\/]+)') { $wt = $Matches[1] }
        elseif ($cmd -match 'TBMS_git[\\/]([^\\/]+)') { $wt = $Matches[1] }
        else { $wt = '?' }

        $pid_i = [int]$p.ProcessId
        $cpu = 0
        if ($perf.ContainsKey($pid_i)) { $cpu = $perf[$pid_i] }

        # Strip non-ASCII: the caller reads this over a pipe whose encoding we
        # do not control, and a mojibake command line is worse than a lossy one
        # (it makes the warning look broken, so people stop trusting it).
        $trimmed = ($cmd -replace '\s+', ' ') -replace '[^\x20-\x7E]', '.'
        if ($trimmed.Length -gt 120) { $trimmed = $trimmed.Substring(0, 120) + '...' }

        # Double quotes on purpose: single-quoted strings do not process the
        # backtick escape, so `t would come out as a literal backtick + t.
        "{0}`t{1}`t{2}`t{3}`t{4}" -f $pid_i, $p.Name, $cpu, $wt, $trimmed
    }

    # Trailing summary line, marked so the caller can tell it apart.
    "#CORES`t{0}" -f $cores
} catch {
    exit 1
}
