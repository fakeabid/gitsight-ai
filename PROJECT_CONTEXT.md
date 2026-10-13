# Project Context — GitSight PR Review Service (LangGraph migration)

This file is the **complete background** for the work described in `IMPLEMENTATION_GUIDE.md`. Read it before touching any code. It contains the original prompt, the original C# code and the sample output **verbatim**, plus everything that was decided, assumed, or discovered while analysing them.

If anything here conflicts with `IMPLEMENTATION_GUIDE.md`, the guide describes the *target*, and this file describes the *source of truth about the existing system and the decisions made*. Raise conflicts instead of silently picking one.

---

## 1. People and roles

| Who | Role |
|---|---|
| The user (our client) | Builds and **hosts** the new FastAPI + LangGraph service. Is doing this on behalf of a friend. |
| The friend | Owns **GitSight** (a .NET + React app). Currently calls Gemini directly from C# with one large prompt. Will call the new service over HTTP instead. |
| The coding agent (Cursor / Antigravity) | Implements the service following `IMPLEMENTATION_GUIDE.md`. |

---

## 2. The product: GitSight

- Web app where users **log in with their GitHub account**.
- It is a **pull-request review system**: for the user's repositories, it reviews a PR with AI and lets the user **view the issues found in their PRs** across their different repositories.
- Backend: ASP.NET Core (C#). Frontend: React (paths in the sample output: `server/GitSight.Api/...`, `client/src/api/axiosClient.jsx`).
- Each stored review session has: `id`, `owner`, `repo`, `prNumber`, counts, `executiveSummary`, `createdAt`, `isTracked`, `isWebhook`, and a list of issues; each stored issue adds `id`, `aiReviewSessionId`, `author` (always `"GitSight AI"`), `isIgnored`, `isCommented`, `createdAt` (see 4.4). **These stored fields are added by the .NET app, not by the AI and not by our service.**

---

## 3. How the existing system works today

1. The .NET app fetches the PR's **unified diff** from GitHub (sample: `PR-8-AI-Review.txt`) and the PR details (title, description).
2. It calls `_geminiService.AnalyzeDiffAsync(diff, prDetails.Title, prDetails.Description)`.
3. `AnalyzeDiffAsync` (verbatim in 4.2):
   1. Fails if the Gemini API key is not configured.
   2. Splits the diff on the substring `diff --git` into per-file parts.
   3. Drops "noise" files (pattern list in section 6) by checking whether the file's header line contains a pattern (case-insensitive).
   4. **Truncates each file's diff to 8,000 characters** (appending a truncation note).
   5. Packs files into chunks of at most `MaxChunkSize` characters, stopping at `MaxTotalChunks` chunks (anything beyond is silently dropped).
   6. If all files were noise, it still sends the **first raw file** truncated to 5,000 chars.
   7. Loops over chunks **sequentially**, calling `AnalyzeChunkAsync(chunk, "<title> (Part i of N)", description)`.
   8. Merges: sums `SyntaxErrorsCount`, `SecurityIssuesCount`, `BreachesCount`, `PerformanceIssuesCount`, `CodeSmellsCount`; concatenates issues; averages `OverallConfidenceScore`; sets `FinalSuggestionsCount = Issues.Count`; sets `ExecutiveSummary` to the **chunk summaries joined with newlines**.
4. `AnalyzeChunkAsync` (verbatim in 4.3) builds one text = system prompt + blank line + user message, posts it to Gemini's REST `generateContent` (temperature 0.2, `responseMimeType = application/json`), **tries a list of fallback models** until one returns success, strips possible markdown fences, deserialises JSON into `GeminiReviewResultDto`, and re-computes some counts from the issue list.
5. The .NET app stores the result and shows it in the UI, adding the extra fields listed in section 2.

---

## 4. Original materials (verbatim, from the user's uploads)

### 4.1 The prompt (`prompt.txt`)

````
 """
        You are GitSight, an expert Senior Principal Software Engineer performing an automated, actionable pull request code review.
        You analyze the provided git diff and identify real, constructive issues across security, correctness, reliability, performance, and code quality.

        ## 1. OUTPUT SPECIFICATION (CRITICAL)
        You MUST respond with a single, raw, valid JSON object ONLY. Do NOT wrap it in markdown block quotes (no json). Do NOT include conversational explanations before or after the JSON.
        The JSON schema MUST strictly follow this structure:
        {
          "issues": [
            {
              "filePath": "relative/path/to/file.ext",
              "startLine": 10,
              "endLine": 12,
              "issueType": "Security" | "Breach" | "Bug" | "Performance" | "CodeSmell",
              "severity": "Critical" | "High" | "Medium" | "Low",
              "comment": "Clear, concise explanation of the issue, why it is dangerous or suboptimal, and how to resolve it.",
              "suggestedRemovedCode": "exact code from diff to be removed/replaced",
              "suggestedAddedCode": "concrete improved replacement code"
            }
          ],
          "executiveSummary": "Concise 2-3 sentence overview of the PR's purpose and code quality assessment.",
          "overallConfidenceScore": 0.95,
          "finalSuggestionsCount": 0,
          "securityIssuesCount": 0,
          "syntaxErrorsCount": 0,
          "breachesCount": 0,
          "bugsCount": 0,
          "performanceIssuesCount": 0,
          "codeSmellsCount": 0,
          "testCoverageImpact": 0.0,
          "codeComplexity": "Low" | "Medium" | "High"
        }

        Important Count Rules:
        - finalSuggestionsCount MUST equal issues.length.
        - securityIssuesCount = count of issues with issueType "Security".
        - breachesCount = count of issues with issueType "Breach".
        - syntaxErrorsCount = 0.
        - performanceIssuesCount = count of issues with issueType "Performance".
        - codeSmellsCount = count of issues with issueType "CodeSmell".
        - (Bugs are counted by issues with issueType "Bug").

        ## 2. CATEGORIES TO IDENTIFY
        Review the added lines ('+') and modified logic carefully for:

        1. SECURITY & BREACHES:
           - Hardcoded secrets, API keys, tokens, credentials, or private keys.
           - Injection vulnerabilities (SQL injection, Command injection, Path traversal, XSS).
           - Insecure deserialization, broken authentication/authorization checks.
           - Sensitive data exposure in logs or API responses.
           - Insecure cryptography, disabled SSL/TLS validation, dangerous CORS.

        2. BUGS & RELIABILITY:
           - Null reference exceptions / unguarded dereferences on optional or nullable values.
           - Logic flaws, inverted boolean conditions, incorrect comparison operators, off-by-one errors.
           - Async/await hazards: unhandled Tasks, missing await, .Result or .Wait() deadlocks, async void.
           - Resource leaks: streams, database connections, HTTP clients, or disposables not properly disposed or using using.
           - Swallowed exceptions, empty catch blocks, or missing error propagation.
           - Concurrency issues: unsynchronized access to shared state or static collections.

        3. PERFORMANCE:
           - N+1 database queries or HTTP calls inside loops.
           - Unbounded queries without pagination, limits, or projections on potentially large collections.
           - Heavy operations, repeated disk/network I/O, or redundant expensive parsing inside tight loops.
           - Synchronous blocking I/O calls on hot request paths.

        4. CODE SMELL & MAINTAINABILITY:
           - Unused variables, dead code, leftover debug statements (console.log, Console.WriteLine).
           - Dangerous anti-patterns, deeply nested conditionals that can be early-exited.
           - Violation of API contracts, inconsistent return types or missing validations on public inputs.

        ## 3. GUIDELINES FOR HIGH QUALITY REVIEWS
        - Anchor issues to changed files (filePath) and accurate line numbers (startLine, endLine) based on the diff hunk (+ lines).
        - Provide actionable, constructive suggestedRemovedCode and suggestedAddedCode whenever possible so the developer can immediately apply the fix.
        - Set severity accurately:
          - "Critical": Remote exploits, credential leak, severe data loss, or crash in core path.
          - "High": Security flaw, serious bug, or major performance bottleneck.
          - "Medium": Logic flaw, unhandled edge cases, or noticeable performance degradation.
          - "Low": Minor code smell, missing cleanup, or non-critical improvement.
        - If the diff has genuinely high quality with no significant defects, report an empty issues list with a positive executiveSummary. But be vigilant and do NOT ignore legitimate bugs, security concerns, or poor practices.
        """
````

### 4.2 The service method that passes the diff and chunks it (`service_function_that_passes_the_diff.txt`)

The first line is the call site; the rest is `AnalyzeDiffAsync`.

````csharp
          analysisDto = await _geminiService.AnalyzeDiffAsync(diff, prDetails.Title, prDetails.Description);





    public async Task<GeminiReviewResultDto> AnalyzeDiffAsync(string diffText, string prTitle, string? prDescription = null)
    {
        _logger.LogInformation("Starting AI Diff analysis. PR Title: {PrTitle}, Diff length: {DiffLength}", prTitle, diffText.Length);
        
        if (string.IsNullOrWhiteSpace(_settings.ApiKey))
        {
            _logger.LogError("Gemini API key is not configured.");
            throw new InvalidOperationException("Gemini API key is not configured. Please set GeminiSettings:ApiKey in appsettings.json or user-secrets.");
        }

        var rawFiles = diffText.Split(new[] { "diff --git" }, StringSplitOptions.RemoveEmptyEntries);
        var relevantFiles = new List<string>();

        foreach (var file in rawFiles)
        {
            var firstLineEnd = file.IndexOf('\n');
            var header = firstLineEnd > 0 ? file.Substring(0, firstLineEnd) : file;

            bool isNoise = NoiseFilePatterns.Any(pattern => header.Contains(pattern, StringComparison.OrdinalIgnoreCase));
            if (isNoise)
            {
                _logger.LogInformation("Skipping generated/noise file in diff: {Header}", header.Trim());
                continue;
            }

            var content = "diff --git" + file;
            if (content.Length > 8000)
            {
                content = content.Substring(0, 8000) + "\n\n... [File diff truncated due to size limits]\n";
            }

            relevantFiles.Add(content);
        }

        var chunks = new List<string>();
        var currentChunk = new StringBuilder();

        foreach (var fileContent in relevantFiles)
        {
            if (chunks.Count >= MaxTotalChunks)
            {
                _logger.LogInformation("Reached max chunk limit ({MaxTotalChunks}) for large PR with {Count} files.", MaxTotalChunks, rawFiles.Length);
                break;
            }

            if (currentChunk.Length + fileContent.Length > MaxChunkSize && currentChunk.Length > 0)
            {
                chunks.Add(currentChunk.ToString());
                currentChunk.Clear();

                if (chunks.Count >= MaxTotalChunks) break;
            }
            
            currentChunk.AppendLine(fileContent);
        }

        if (currentChunk.Length > 0 && chunks.Count < MaxTotalChunks)
        {
            chunks.Add(currentChunk.ToString());
        }

        // If all files were filtered as noise, retain at least a summary chunk of the first relevant raw file
        if (chunks.Count == 0 && rawFiles.Length > 0)
        {
            chunks.Add("diff --git" + (rawFiles[0].Length > 5000 ? rawFiles[0].Substring(0, 5000) : rawFiles[0]));
        }

        var masterResult = new GeminiReviewResultDto
        {
            Issues = new List<GeminiInlineCommentDto>()
        };
        var summaries = new StringBuilder();

        for (int i = 0; i < chunks.Count; i++)
        {
            var chunkTitle = $"PULL REQUEST TITLE: {prTitle} (Part {i + 1} of {chunks.Count})";
            var chunkResult = await AnalyzeChunkAsync(chunks[i], chunkTitle, prDescription);

            summaries.AppendLine(chunkResult.ExecutiveSummary);
            masterResult.SyntaxErrorsCount += chunkResult.SyntaxErrorsCount;
            masterResult.SecurityIssuesCount += chunkResult.SecurityIssuesCount;
            masterResult.BreachesCount += chunkResult.BreachesCount;
            masterResult.PerformanceIssuesCount += chunkResult.PerformanceIssuesCount;
            masterResult.CodeSmellsCount += chunkResult.CodeSmellsCount;

            if (chunkResult.Issues != null)
            {
                masterResult.Issues.AddRange(chunkResult.Issues);
            }

            masterResult.OverallConfidenceScore += chunkResult.OverallConfidenceScore;
        }

        if (chunks.Count > 0)
        {
            masterResult.OverallConfidenceScore /= chunks.Count;
        }

        masterResult.FinalSuggestionsCount = masterResult.Issues.Count;
        masterResult.ExecutiveSummary = summaries.ToString().Trim();

        _logger.LogInformation("Completed Gemini AI Diff analysis. Extracted {TotalIssues} total issues across {ChunkCount} chunks.", masterResult.Issues.Count, chunks.Count);

        return masterResult;
    }
````

### 4.3 The per-chunk AI call (`looped_function_that_calls_AI.txt`)

````csharp
    private async Task<GeminiReviewResultDto> AnalyzeChunkAsync(string diffChunk, string prTitle, string? prDescription)
    {
        var systemPrompt = GeminiPrompts.SystemPrompt;
        var userMessage = 
$"""
        PULL REQUEST TITLE: {prTitle}
        PULL REQUEST DESCRIPTION: {prDescription ?? "No description provided."}
        UNIFIED DIFF:
        {diffChunk}
        """;
        var payload = new
        {
            contents = new[]
            {
                new
                {
                    parts = new[]
                    {
                        new { text = $"{systemPrompt}\n\n{userMessage}" }
                    }
                }
            },
            generationConfig = new
            {
                temperature = 0.2,
                responseMimeType = "application/json"
            }
        };
        var primaryModel = string.IsNullOrWhiteSpace(_settings.Model) ? "gemini-3.8-flash" : _settings.Model;
        var modelsToTry = new[] { primaryModel, "gemini-3.8-flash", "gemini-3.5-flash", "gemini-flash-latest" }
            .Distinct()
            .ToArray();
        
        HttpResponseMessage? response = null;
        string currentModel = primaryModel;
        
        for (int i = 0; i < modelsToTry.Length; i++)
        {
            currentModel = modelsToTry[i];
            var url = $"https://generativelanguage.googleapis.com/v1beta/models/{currentModel}:generateContent?key={_settings.ApiKey}";
            
            using var request = new HttpRequestMessage(HttpMethod.Post, url);
            request.Content = new StringContent(JsonSerializer.Serialize(payload), Encoding.UTF8, "application/json");
            response = await _httpClient.SendAsync(request);
            
            if (response.IsSuccessStatusCode)
            {
                break;
            }
            
            var err = await response.Content.ReadAsStringAsync();
            _logger.LogWarning("Gemini API call to {Model} returned {StatusCode}: {Error}", currentModel, response.StatusCode, err);
            if (i == modelsToTry.Length - 1)
            {
                throw new HttpRequestException($"Failed to analyze diff with Gemini API. Exhausted all fallback models. Last error ({currentModel}): {response.StatusCode} - {err}");
            }
        }
        var json = await response!.Content.ReadAsStringAsync();
        using var doc = JsonDocument.Parse(json);
        
        var text = doc.RootElement
            .GetProperty("candidates")[0]
            .GetProperty("content")
            .GetProperty("parts")[0]
            .GetProperty("text")
            .GetString();
        if (string.IsNullOrWhiteSpace(text))
        {
            throw new InvalidOperationException("Empty response received from Gemini.");
        }
        var cleanedText = text.Trim();
        if (cleanedText.StartsWith("```json"cleanedText = cleanedText.Substring(7);
        if (cleanedText.StartsWith("```")) cleaText = cleanedText.Substring(3);
        if (cleanedText.EndsWith("```")) cleaText = cleanedText.Substring(0, cleanedText.Length - 3);        cleanedText = cleanedText.Trim();
        var result = JsonSerializer.Deserialize<GeminiReviewResultDto>(cleanedText, new JsonSerializerOptions
        {
            PropertyNameCaseInsensitive = true
        });
        if (result == null)
        {
            throw new InvalidOperationException("Failed to deserialize Gemini output.");
        }
        result.Issues ??= new List<GeminiInlineCommentDto>();
        // Normalize counts to match parsed issues
        result.FinalSuggestionsCount = result.Issues.Count;
        result.SecurityIssuesCount = result.Issues.Count(i => i.IssueType.Equals("Security", StringComparison.OrdinalIgnoreCase));
        result.BreachesCount = result.Issues.Count(i => i.IssueType.Equals("Breach", StringComparison.OrdinalIgnoreCase));
        result.PerformanceIssuesCount = result.Issues.Count(i => i.IssueType.Equals("Performance", StringComparison.OrdinalIgnoreCase));
        result.CodeSmellsCount = result.Issues.Count(i => i.IssueType.Equals("CodeSmell", StringComparison.OrdinalIgnoreCase));
        _logger.LogInformation("Gemini model {Model} successfully extracted {Count} issues for chunk.", currentModel, result.Issues.Count);
        return result;
    }
````

### 4.4 A sample of the stored output (`output_example.txt`)

This is what the .NET app returns/stores **after** it has added its own fields. It is a different PR (repo `gitsight`, PR 29) from the sample diff in 4.5, so the two files are **not** an input/output pair.

````json
    "data": {
        "id": "fcf42e4e-2975-4f26-8f11-3b4c921f8c22",
        "owner": "Abhiram4068",
        "repo": "gitsight",
        "prNumber": 29,
        "finalSuggestionsCount": 3,
        "securityIssuesCount": 1,
        "syntaxErrorsCount": 0,
        "breachesCount": 2,
        "performanceIssuesCount": 0,
        "codeSmellsCount": 0,
        "testCoverageImpact": 0.00,
        "codeComplexity": "",
        "overallConfidenceScore": 1.00,
        "executiveSummary": "The PR introduces hardcoded secrets in both the client-side code and server-side configuration, and includes an unsafe use of eval(). These issues pose significant security risks and must be addressed before merging.\r\n",
        "createdAt": "2026-10-10T09:53:14.883727",
        "isTracked": true,
        "isWebhook": false,
        "issues": [
            {
                "id": "a293e73b-7eff-466a-83b8-1e097ea504ab",
                "aiReviewSessionId": "fcf42e4e-2975-4f26-8f11-3b4c921f8c22",
                "filePath": "server/GitSight.Api/appsettings.json",
                "startLine": 11,
                "endLine": 11,
                "author": "GitSight AI",
                "comment": "Remove hardcoded secrets from configuration files. Use environment variables or a secure secret store like Azure Key Vault.",
                "issueType": "Breach",
                "severity": "High",
                "suggestedRemovedCode": "\"ClientSecret\": \"cdd84c8e6bb9771bb2866552d21606885f30d66b\",",
                "suggestedAddedCode": "\"ClientSecret\": \"${GITHUB_CLIENT_SECRET}\",",
                "isIgnored": false,
                "isCommented": true,
                "createdAt": "2026-10-10T09:53:14.8859234"
            },
            {
                "id": "5f847b6d-0150-4cf5-b76e-40b3287c61c2",
                "aiReviewSessionId": "fcf42e4e-2975-4f26-8f11-3b4c921f8c22",
                "filePath": "client/src/api/axiosClient.jsx",
                "startLine": 12,
                "endLine": 12,
                "author": "GitSight AI",
                "comment": "Hardcoded secrets should not be committed to version control. Use environment variables or a secret management service.",
                "issueType": "Breach",
                "severity": "High",
                "suggestedRemovedCode": "const API_KEY_SECRET = \"sk-fake-secret-key-12345\"; // Hardcoded secret",
                "suggestedAddedCode": "const API_KEY_SECRET = process.env.API_KEY_SECRET;",
                "isIgnored": false,
                "isCommented": true,
                "createdAt": "2026-10-10T09:53:14.8844946"
            },
            {
                "id": "f2bf14d9-86d5-4a6c-877a-5cf9650f9d66",
                "aiReviewSessionId": "fcf42e4e-2975-4f26-8f11-3b4c921f8c22",
                "filePath": "client/src/api/axiosClient.jsx",
                "startLine": 14,
                "endLine": 14,
                "author": "GitSight AI",
                "comment": "Avoid using eval() as it poses a significant security risk. Replace with direct function calls or standard logic.",
                "issueType": "Security",
                "severity": "High",
                "suggestedRemovedCode": "eval(\"console.log('dangerous')\"); // Security risk",
                "suggestedAddedCode": "console.log('dangerous');",
                "isIgnored": false,
                "isCommented": true,
                "createdAt": "2026-10-10T09:53:14.8859222"
            }
        ]
    },
````

### 4.5 Sample input diff (`PR-8-AI-Review.txt`)

A real unified diff fetched from GitHub by the .NET app (a Google Apps Script backend + React task list, unrelated to GitSight itself). It is **not embedded here** because of its size (25 KB); copy the file to `tests/fixtures/sample_pr.diff` in the new repo (the tests use it if present).

| File | Characters | Added lines | Removed lines | Hunks | New file |
|---|---:|---:|---:|---:|---|
| `Standup/server.gs` | 12,833 | 518 | 0 | 1 | yes |
| `Standup/src/index.css` | 762 | 17 | 0 | 2 | no |
| `Standup/src/pages/TaskList.jsx` | 10,786 | 57 | 4 | 17 | no |
| `Standup/src/services/api.js` | 731 | 2 | 0 | 2 | no |
| **Total** | **25,112** | | | | |

Observations that matter for the design:
- `Standup/server.gs` is a **new file with a single 518-line hunk** (`@@ -0,0 +1,518 @@`) and is the first file in the diff. Under the C# rules it is cut at 8,000 characters, so the later part of the file is **never reviewed**.
- The whole diff is larger than one 15,000-character chunk, so it needs at least 2 chunks.
- No file in this sample matches the noise patterns.

---

## 5. Analysis of the existing implementation (facts and defects found)

Read from the verbatim code above. Items marked *(paste?)* may be copy/paste artefacts rather than real bugs.

**Behaviour**
1. Chunks are processed **sequentially** → latency grows linearly with the number of chunks.
2. The system prompt is concatenated with the user message into a single text part (no separate system instruction).
3. Model fallback happens only on a **non-success HTTP status**; network exceptions are not caught. The API key is placed in the URL query string.
4. Chunk labelling bug: the caller passes `"PULL REQUEST TITLE: <title> (Part i of N)"` as the title, and `AnalyzeChunkAsync` prefixes `PULL REQUEST TITLE:` again → the prompt contains the label twice.
5. **Per-file truncation at 8,000 characters** silently discards the rest of large files. **`MaxTotalChunks`** silently discards whole files beyond the limit. Neither is reported to the user.
6. If every file is noise, the **first raw file** (a noise file) is still sent to the model.
7. Noise matching uses a **substring** test on the header line, so `build/` also matches e.g. `rebuild/…`, `bin/` also matches `cabin/…`.
8. `BugsCount` is **not summed** into the merged result (and not recomputed per chunk); the stored sample has no `bugsCount`. `CodeComplexity` and `TestCoverageImpact` requested by the prompt are **never merged** (the stored sample shows `"codeComplexity": ""` and `testCoverageImpact: 0.00`).
9. The merged `ExecutiveSummary` is the chunk summaries joined with `AppendLine`, so it ends with a line break (the sample's summary ends with `\r\n`) and reads as several unrelated summaries for multi-chunk PRs.
10. A failure in any chunk **throws** and fails the entire review.
11. Fence stripping: `cleaText` is assigned but `cleanedText` is used afterwards, and one `StartsWith(` is missing its closing parenthesis *(paste?)*; as written the stripping would not work. The prompt demands raw JSON anyway.
12. The prompt asks the model to produce counts, then C# overwrites most of them — duplicated responsibility.

**How `issueType` is really used** (from the sample output): `"Breach"` = hardcoded secrets/credentials; `"Security"` = other vulnerabilities such as `eval()`. The original prompt does not define the difference; the new prompt does.

**Line-number anchoring:** issues are anchored to the **new file's** line numbers (`startLine`/`endLine`) because the UI posts them as inline comments, so accuracy of those numbers matters.

---

## 6. Confirmed constants and decisions (provided by the user)

| Item | Value |
|---|---|
| Noise patterns (21) | `package-lock.json`, `yarn.lock`, `pnpm-lock.yaml`, `composer.lock`, `Cargo.lock`, `packages.lock.json`, `.Designer.cs`, `.generated.cs`, `.min.js`, `.min.css`, `.map`, `/Migrations/`, `dist/`, `build/`, `bin/`, `obj/`, `.svg`, `.png`, `.jpg`, `.jpeg`, `.ico` |
| `MaxChunkSize` | **15,000** characters |
| `MaxTotalChunks` | **5** |
| LLM provider | **Gemini**, staying on Gemini |
| API key | A **free Google AI Studio key** |
| Model strategy | Primary model **with fallback models** (names in the C# code: primary default `gemini-3.8-flash`, then `gemini-3.8-flash`, `gemini-3.5-flash`, `gemini-flash-latest`). The names could not be verified by the author of this document. |
| Temperature | 0.2 (from the C# code) |
| Streaming | **No** (not for now) |
| Technology | **FastAPI + LangGraph**, Python |
| Who calls the service | The friend's .NET app, over HTTP |

## 7. Assumptions made (not confirmed — flag if wrong)

1. The service is **stateless**: no database, no checkpointer, no result caching. (The user was asked and did not specify persistence.)
2. The .NET app **sends the diff** in the request; the service never calls GitHub. (Matches the sample files: the diff is fetched by the .NET app.)
3. **Hosting platform is undecided** (Render / Railway / Fly.io / VPS were offered). The design is container-based and platform-neutral.
4. The response keeps the **top-level shape of `GeminiReviewResultDto`** so the C# change is minimal; extra data goes in a new `meta` object.
5. `testCoverageImpact` is a float in `[-1, 1]` (meaning unknown; the original always produced 0).
6. Synchronous request/response is acceptable (a review of ≤ 5 chunks in parallel should finish within the timeout).

---

## 8. What is being built (summary)

A hosted service with one main endpoint, `POST /v1/reviews`, which:
1. Receives `{prTitle, prDescription, diff}`.
2. **prepare_chunks** – filters noise, splits oversized files at hunk boundaries (rewriting `@@` headers), packs into ≤ 15,000-char chunks, max 5.
3. **analyze_chunk × N (parallel, via `Send`)** – each chunk: build prompt → call Gemini with **structured output** and model fallbacks → validate/sanitize → retry up to 2 times → else record failure.
4. **aggregate** – merge, dedupe, sort by severity, derive all counts, mean confidence, max complexity.
5. **synthesize_summary** – one LLM call to write a coherent summary (skipped when ≤ 1 chunk succeeded).
6. Returns the review in the existing DTO shape + `meta`.

Full details, code, tests, deployment: `IMPLEMENTATION_GUIDE.md`.

The earlier design discussion produced two diagrams: (1) an overview of the main graph (`prepare_chunks` → parallel `analyze_chunk` → `aggregate` → `synthesize_summary`) and (2) the `analyze_chunk` subgraph (`build_prompt` → `call_llm` → `validate`, with a bounded retry loop, ending in a chunk result or a chunk failure). One refinement since then: complexity and test-coverage impact are produced per chunk and combined in `aggregate`; `synthesize_summary` only writes the summary.

---

## 9. Non-goals
Streaming, background jobs / polling, authentication of end users, GitHub API access, persistence, a UI, multi-provider support (the LLM factory keeps a later switch cheap), webhooks.

---

## 10. Quality bar (what "good" means for this project)
- **Clean architecture:** DRY, separation of concerns, thin routes, injected dependencies, one place per responsibility (see guide sections 3 and 8).
- **Tests are mandatory** and the only proof of correctness — **no code has been executed yet** (guide section 10).
- Behaviour must be **at least as good as the C# version** and strictly better on the defects listed in section 5.
- Never log or commit secrets or diff contents.

---

## 11. Open questions for the user / friend
1. Which hosting platform will be used (affects cold-start and timeout advice)?
2. What does the UI expect from `testCoverageImpact` and `codeComplexity`?
3. Should PRs larger than 5 chunks be reviewed in full (raise limits) or keep the current cap (now reported in `meta.skippedFiles`)?
4. Exact Gemini model names currently available on the user's AI Studio key.
5. Does the .NET `GeminiReviewResultDto` tolerate an extra `meta` object? (`System.Text.Json` ignores unknown properties by default.)

---

## 12. Glossary
- **Diff / unified diff:** text output of `git diff`; one `diff --git` block per file, containing hunks starting with `@@ -old,count +new,count @@`.
- **Hunk:** a contiguous changed region of a file.
- **Chunk:** a group of file diffs small enough (≤ 15,000 chars) to send to the model in one call.
- **Noise file:** generated, binary, lock or build-output file that is not worth reviewing.
- **LangGraph:** library for building stateful, graph-shaped LLM workflows; **`Send`** fans work out to parallel node instances; a **reducer** merges results from parallel branches.
- **Structured output:** asking the model to return data matching a schema (here a Pydantic model) instead of free text.
- **Breach / Security:** this project's two security issue types (secrets vs other vulnerabilities).

---

## 13. Status at the time this document was written
- Analysis of all five uploaded files: **done**.
- Architecture and both diagrams: **done and agreed** in conversation.
- Implementation guide with reference code and a full test plan: **written**.
- Source code: **not built or executed.** (A partial scaffold was started in a scratch sandbox and then deliberately discarded at the user's request; nothing from it is relied on.) The reference code in the guide is unexecuted; the **test suite must be written and run** before anything is considered working.
- Nothing has been deployed.
