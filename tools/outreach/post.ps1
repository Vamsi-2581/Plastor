# 구인글 올리기 CLI.
# 사용:
#   pwsh tools/outreach/post.ps1 list                 글 목록과 상태(승인·올림)
#   pwsh tools/outreach/post.ps1 approve <파일|all>   글 전체를 보고 사람이 yes 를 쳐서 승인(한 번만)
#   pwsh tools/outreach/post.ps1 run [-DryRun] [-NoWatch]  승인된 글을 묻지 않고 처리(y 자동), 이어서 watch
#   pwsh tools/outreach/post.ps1 watch [-Minutes 30]  공개 검색·피드에서 올라간 글을 찾아 주소를 기록
#   pwsh tools/outreach/post.ps1 done <파일> <주소>   찾지 못한 글의 주소를 손으로 기록
# 승인은 글 내용의 SHA-256 에 묶인다. 한 글자라도 바뀌면 승인이 풀린다.
# approve 는 키보드 입력이 있는 터미널에서만 된다(입력이 넘겨진 자동 실행, 곧 AI 에이전트는 승인할 수 없다).
# API 가 있는 곳(github-discussion)은 끝까지 올린다. API 가 없는 곳(hn·reddit·geeknews)은 제목·본문을 미리 채운
# 글쓰기 탭을 한꺼번에 연다. 사람이 할 일은 탭마다 '게시' 한 번: 이 사이트들은 자동 게시를 금지한다.
param(
    [Parameter(Position = 0)][ValidateSet('list', 'approve', 'run', 'watch', 'done')][string]$Command = 'list',
    [Parameter(Position = 1)][string]$Target,
    [Parameter(Position = 2)][string]$Url,
    [switch]$DryRun,
    [switch]$NoWatch,
    [int]$Minutes = 30
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8

$PostsDir = Join-Path $PSScriptRoot 'posts'
# 승인·기록은 저장소 밖(사용자 프로필)에 둔다: 공개본에 올라가지 않고, 저장소를 지워도 남는다
$Store = Join-Path $HOME '.modelerharness/outreach'
$ApprovedFile = Join-Path $Store 'approved.json'
$LogFile = Join-Path $Store 'posted.jsonl'
New-Item -ItemType Directory -Force $Store | Out-Null

function Read-Post([string]$path) {
    $raw = [IO.File]::ReadAllText($path, [Text.Encoding]::UTF8).Replace("`r`n", "`n")
    if ($raw -notmatch '(?s)^---\n(.*?)\n---\n(.*)$') { throw "머리말(---) 형식이 아님: $path" }
    # 아래 줄별 -match 가 $Matches 를 덮어쓰므로 먼저 꺼내 둔다
    $head = $Matches[1]; $body = $Matches[2].Trim()
    $meta = @{}
    foreach ($line in $head -split "`n") {
        if ($line -match '^(\w[\w-]*):\s*(.*)$') { $meta[$Matches[1]] = $Matches[2].Trim() }
    }
    foreach ($k in 'channel', 'target', 'title') { if (-not $meta[$k]) { throw "$path 에 $k 가 없음" } }
    $sha = [BitConverter]::ToString([Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($raw))).Replace('-', '').ToLower()
    [pscustomobject]@{ File = Split-Path $path -Leaf; Meta = $meta; Body = $body; Sha = $sha }
}

function Get-Approved {
    if (Test-Path $ApprovedFile) { Get-Content $ApprovedFile -Raw | ConvertFrom-Json -AsHashtable } else { @{} }
}

function Get-Posted {
    $h = @{}
    if (Test-Path $LogFile) { Get-Content $LogFile | Where-Object { $_ } | ForEach-Object { $e = $_ | ConvertFrom-Json; $h[$e.sha] = $e } }
    $h
}

function Write-Log($post, [string]$state, [string]$where) {
    $e = [ordered]@{ time = (Get-Date).ToString('s'); file = $post.File; sha = $post.Sha; channel = $post.Meta.channel; target = $post.Meta.target; state = $state; url = $where }
    Add-Content $LogFile ($e | ConvertTo-Json -Compress)
}

function Test-Post($post) {
    # 올리기 전 검사: 사이트 제한을 넘는 글은 FAIL
    $problems = @()
    if ($post.Meta.channel -eq 'hn' -and $post.Meta.title.Length -gt 80) { $problems += "HN 제목 $($post.Meta.title.Length)자 > 80자" }
    if ($post.Meta.channel -eq 'reddit' -and $post.Meta.title.Length -gt 300) { $problems += "Reddit 제목 > 300자" }
    if ($post.Meta.channel -in 'hn', 'geeknews' -and -not $post.Meta.url) { $problems += "$($post.Meta.channel) 는 url 이 필요" }
    if ($post.Meta.channel -notin 'github-discussion', 'hn', 'reddit', 'geeknews') { $problems += "모르는 channel: $($post.Meta.channel)" }
    $problems
}

function Get-Posts {
    $files = Get-ChildItem $PostsDir -Filter *.md | Sort-Object Name
    if ($Target -and $Target -ne 'all') { $files = $files | Where-Object { $_.Name -eq $Target -or $_.BaseName -eq $Target } }
    if (-not $files) { throw "글 파일 없음: $Target" }
    $files | ForEach-Object { Read-Post $_.FullName }
}

function Send-Discussion($post) {
    $repo = gh api graphql -f query='{repository(owner:"endlessGold",name:"Plastor"){id discussionCategories(first:25){nodes{id name}}}}' | ConvertFrom-Json
    $cat = $repo.data.repository.discussionCategories.nodes | Where-Object name -eq $post.Meta.target
    if (-not $cat) { throw "토론 분류 없음: $($post.Meta.target)" }
    $q = 'mutation($r:ID!,$c:ID!,$t:String!,$b:String!){createDiscussion(input:{repositoryId:$r,categoryId:$c,title:$t,body:$b}){discussion{url}}}'
    $res = gh api graphql -f query=$q -f r=$($repo.data.repository.id) -f c=$($cat.id) -f t=$($post.Meta.title) -f b=$($post.Body) | ConvertFrom-Json
    if (-not $res.data.createDiscussion.discussion.url) { throw "토론 만들기 실패: $($res | ConvertTo-Json -Depth 6 -Compress)" }
    $res.data.createDiscussion.discussion.url
}

function Open-Compose($post) {
    function e([string]$s) { [Uri]::EscapeDataString($s) }
    switch ($post.Meta.channel) {
        # HN 링크 글: 제목·주소가 채워지므로 submit 만 누르면 된다(본문은 선택이라 넣지 않는다)
        'hn' { "https://news.ycombinator.com/submitlink?u=$(e $post.Meta.url)&t=$(e $post.Meta.title)" }
        # 옛 Reddit 글쓰기 주소: 로그인을 거쳐도 title·text 값이 따라간다(2026-10-30 확인)
        'reddit' { "https://old.reddit.com/r/$($post.Meta.target)/submit?selftext=true&title=$(e $post.Meta.title)&text=$(e $post.Body)" }
        # GeekNews 가 url·title 을 미리 채우는지는 UNKNOWN. 안 채우면 클립보드 본문과 화면 안내로 넣는다
        'geeknews' { "https://news.hada.io/write?url=$(e $post.Meta.url)&title=$(e $post.Meta.title)" }
    }
}

function Get-Text($node) {
    # 피드의 title·link 는 글자일 수도, 속성이 붙은 XML 요소일 수도 있다. 요소를 문자열로 바꾸면 "System.Xml.XmlElement" 가 되어 모든 글과 일치해 버린다
    if ($null -eq $node) { return '' }
    if ($node -is [string]) { return $node }
    if ($node -is [Xml.XmlNode]) { return $node.InnerText }
    "$node"
}

function Find-Posted($post, [datetime]$since) {
    # 공개 검색·피드에서 이 글을 찾는다. 찾으면 주소, 못 찾으면 $null. 네트워크 오류는 이번 회차만 건너뛴다
    $ua = @{ 'User-Agent' = 'Mozilla/5.0 Plastor-outreach (github.com/endlessGold/Plastor)' }
    try {
        switch ($post.Meta.channel) {
            'hn' {
                $r = Invoke-RestMethod "https://hn.algolia.com/api/v1/search_by_date?tags=story&query=$([Uri]::EscapeDataString('Plastor'))" -Headers $ua
                $hit = $r.hits | Where-Object { $_.url -eq $post.Meta.url -and ([datetime]$_.created_at).ToUniversalTime() -ge $since.ToUniversalTime().AddMinutes(-5) } | Select-Object -First 1
                if ($hit) { return "https://news.ycombinator.com/item?id=$($hit.objectID)" }
            }
            'reddit' {
                $x = [xml](Invoke-WebRequest "https://www.reddit.com/r/$($post.Meta.target)/new/.rss?limit=50" -Headers $ua).Content
                $hit = $x.feed.entry | Where-Object { (Get-Text $_.title).Trim() -eq $post.Meta.title } | Select-Object -First 1
                if ($hit) { return $hit.link.href }
            }
            'geeknews' {
                $x = [xml](Invoke-WebRequest 'https://feeds.feedburner.com/geeknews-feed' -Headers $ua).Content
                $items = @($x.rss.channel.item) + @($x.feed.entry) | Where-Object { $_ }
                $want = ($post.Meta.title -replace '^Show GN:\s*', '').Trim()
                if ($want.Length -lt 10) { return $null }   # 너무 짧은 제목은 남의 글과 섞일 수 있어 찾지 않는다
                $hit = $items | Where-Object { (Get-Text $_.title).Contains($want) } | Select-Object -First 1
                if ($hit) { return $(if ($hit.link.href) { $hit.link.href } else { Get-Text $hit.link }) }
            }
        }
    } catch { Write-Host "  ($($post.Meta.channel) 조회 실패, 다음 회차에 다시: $($_.Exception.Message))" -ForegroundColor DarkGray }
    $null
}

function Invoke-Watch([int]$minutes) {
    # 글쓰기 탭을 연 뒤 아직 '올림'이 아닌 글을 30초마다 찾는다
    $po = Get-Posted
    $wait = @(Get-Posts | Where-Object { $po[$_.Sha] -and $po[$_.Sha].state -ne '올림' })
    if (-not $wait) { Write-Host '기다릴 글 없음'; return }
    $since = [datetime]($wait | ForEach-Object { $po[$_.Sha].time } | Sort-Object | Select-Object -First 1)
    $until = (Get-Date).AddMinutes($minutes)
    Write-Host "올라간 글을 찾는 중(30초마다, Reddit 은 요청 제한 때문에 2분마다, 최대 $minutes 분): $($wait.File -join ', ')"
    $round = 0
    while ($wait -and (Get-Date) -lt $until) {
        foreach ($p in @($wait)) {
            if ($p.Meta.channel -eq 'reddit' -and ($round % 4) -ne 0) { continue }
            $u = Find-Posted $p $since
            if ($u) {
                Write-Log $p '올림' $u
                Write-Host "$($p.File): 올라감 → $u" -ForegroundColor Green
                $wait = @($wait | Where-Object File -ne $p.File)
            }
        }
        if ($wait) { Start-Sleep 30; $round++ }
    }
    foreach ($p in $wait) { Write-Host "$($p.File): $minutes 분 안에 못 찾음. 올렸다면: pwsh tools/outreach/post.ps1 done $($p.File) <주소>" -ForegroundColor Yellow }
}

switch ($Command) {
    'list' {
        $ap = Get-Approved; $po = Get-Posted
        Get-Posts | ForEach-Object {
            $state = if ($po[$_.Sha]) { $po[$_.Sha].state } elseif ($ap[$_.Sha]) { '승인됨' } elseif ($ap.Values | Where-Object file -eq $_.File) { '승인 풀림(내용 바뀜)' } else { '승인 안 됨' }
            $bad = Test-Post $_
            [pscustomobject]@{ 파일 = $_.File; 채널 = "$($_.Meta.channel)/$($_.Meta.target)"; 상태 = $state; 검사 = $(if ($bad) { 'FAIL: ' + ($bad -join '; ') } else { 'PASS' }) }
        } | Format-Table -AutoSize
    }
    'approve' {
        if ([Console]::IsInputRedirected) { [Console]::Error.WriteLine('승인은 키보드로 직접 입력하는 터미널에서만 된다(자동 실행은 승인할 수 없음).'); exit 2 }
        $ap = Get-Approved
        foreach ($p in Get-Posts) {
            $bad = Test-Post $p
            Write-Host "`n==================== $($p.File) → $($p.Meta.channel)/$($p.Meta.target)" -ForegroundColor Cyan
            Write-Host "제목: $($p.Meta.title)"
            if ($p.Meta.url) { Write-Host "주소: $($p.Meta.url)" }
            Write-Host "--------------------`n$($p.Body)`n--------------------"
            if ($bad) { Write-Host "검사 FAIL: $($bad -join '; ') → 승인할 수 없음. 글을 고친 뒤 다시." -ForegroundColor Red; continue }
            if ((Read-Host '이 글을 이 계정으로 올려도 됩니까? 그렇다면 yes') -ceq 'yes') {
                $ap[$p.Sha] = @{ file = $p.File; time = (Get-Date).ToString('s') }
                Write-Host '승인 기록함' -ForegroundColor Green
            } else { Write-Host '건너뜀' }
        }
        $ap | ConvertTo-Json -Depth 4 | Set-Content $ApprovedFile -Encoding utf8
    }
    'run' {
        $ap = Get-Approved; $po = Get-Posted; $n = 0; $tabs = @()
        foreach ($p in Get-Posts) {
            if ($po[$p.Sha] -and $po[$p.Sha].state -eq '올림') { Write-Host "$($p.File): 이미 올라감($($po[$p.Sha].url))"; continue }
            if (-not $ap[$p.Sha]) { Write-Host "$($p.File): 승인 안 됨, 건너뜀(approve 먼저)" -ForegroundColor Yellow; continue }
            $bad = Test-Post $p
            if ($bad) { Write-Host "$($p.File): 검사 FAIL: $($bad -join '; ')" -ForegroundColor Red; continue }
            $n++
            if ($p.Meta.channel -eq 'github-discussion') {
                if ($DryRun) { Write-Host "[미리보기] GitHub 토론 '$($p.Meta.target)' 에 올림: $($p.Meta.title)"; continue }
                $u = Send-Discussion $p
                Write-Log $p '올림' $u
                Write-Host "$($p.File): 올림 → $u" -ForegroundColor Green
            } else {
                $tabs += [pscustomobject]@{ Post = $p; Url = (Open-Compose $p) }
            }
        }
        if ($tabs) {
            # 탭을 한꺼번에 연다. 클립보드는 하나뿐이라, 미리 채우기가 확실하지 않은 GeekNews 본문을 넣는다
            $clip = $tabs | Where-Object { $_.Post.Meta.channel -eq 'geeknews' } | Select-Object -First 1
            if ($DryRun) {
                $tabs | ForEach-Object { Write-Host "[미리보기] 탭: $($_.Url.Substring(0, [Math]::Min(150, $_.Url.Length)))…" }
                if ($clip) { Write-Host "[미리보기] 클립보드: GeekNews 본문 $($clip.Post.Body.Length)자" }
            } else {
                if ($clip) { Set-Clipboard -Value $clip.Post.Body }
                foreach ($t in $tabs) { Start-Process $t.Url; Write-Log $t.Post '글쓰기 화면 엶' $t.Url; Start-Sleep -Milliseconds 700 }
                Write-Host "`n브라우저에 탭 $($tabs.Count)개를 열었다. 탭마다 할 일:" -ForegroundColor Green
                foreach ($t in $tabs) {
                    switch ($t.Post.Meta.channel) {
                        'hn' { Write-Host '  HN       : 제목·주소가 채워져 있음 → submit' }
                        'reddit' { Write-Host '  Reddit   : 제목·본문이 채워져 있음 → (필요하면 flair 고르기) → submit' }
                        'geeknews' { Write-Host "  GeekNews : 제목·주소가 비어 있으면 넣기(제목: $($t.Post.Meta.title) / 주소: $($t.Post.Meta.url)), 본문 칸에 Ctrl+V → 등록" }
                    }
                }
                Write-Host '  처음이면 각 사이트에서 로그인(또는 가입)을 먼저 한다. 로그인 뒤에도 Reddit 은 채운 내용이 유지된다.'
            }
        }
        if (-not $n) { Write-Host '처리할 승인된 글 없음' }
        elseif ($tabs -and -not $DryRun -and -not $NoWatch) { Invoke-Watch $Minutes }
    }
    'watch' { Invoke-Watch $Minutes }
    'done' {
        if (-not $Url) { throw '사용: done <파일> <올라간 주소>' }
        $p = Get-Posts | Select-Object -First 1
        Write-Log $p '올림' $Url
        Write-Host "$($p.File): 올림으로 기록 → $Url"
    }
}
