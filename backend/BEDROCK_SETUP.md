# Amazon Bedrock — NatMedSol AI Setup

The NatMedSol application uses **Amazon Bedrock** as its only AI provider.
There is no Anthropic direct integration, no Emergent proxy, no OpenAI, and
no browser-side AI. All AI calls funnel through `backend/llm_client.py` →
`complete_text()` → the Bedrock Runtime.

Authentication is performed by the **EC2 instance IAM role**. Static AWS
credentials must never be added to `.env`, the codebase, the frontend, or
process environment.

---

## 1. Environment variables (non-secret)

Add to `backend/.env`:

```
AI_ENABLED=true
AI_PROVIDER=bedrock
AWS_REGION=us-east-1
BEDROCK_MODEL_ID=<model-id-or-inference-profile-arn>
AI_REQUEST_TIMEOUT_SECONDS=90
```

- `AI_ENABLED=false` disables AI entirely and fails all calls with a safe
  `ai_disabled` error.
- `AI_PROVIDER` only accepts `bedrock`. Any other value causes the client to
  return `misconfigured` and refuse to send prompts.
- `AWS_REGION` must be a region where the chosen model is enabled.
- `BEDROCK_MODEL_ID` is either the plain model id (e.g.
  `anthropic.claude-sonnet-4-5-20250929-v1:0`) or an inference-profile ARN.
- `AI_REQUEST_TIMEOUT_SECONDS` bounds each Bedrock request.

**Do not add:**
`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`, any
Anthropic key, any Emergent key, any OpenAI key.

---

## 2. Minimum IAM policy (attach to the EC2 instance role)

Scope the policy to the exact model or inference-profile ARN the app uses.
Streaming is **not** implemented; do not add
`bedrock:InvokeModelWithResponseStream`.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowNMSInvokeModel",
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel",
        "bedrock:Converse"
      ],
      "Resource": [
        "arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-sonnet-4-5-20250929-v1:0",
        "arn:aws:bedrock:us-east-1:<account-id>:inference-profile/<profile-id>"
      ]
    }
  ]
}
```

- Replace `us-east-1`, the model id, and the inference-profile ARN with the
  values your organization has enabled.
- If you use only a foundation model, omit the inference-profile ARN.
- If you use only an inference profile, keep just that ARN.

**Do NOT** grant `bedrock:*` or `Resource: "*"`. Least privilege is a
compliance requirement of the AI Sprint charter.

---

## 3. Model access approval

Model access in Bedrock is **not** granted automatically — an AWS console
operator must request access for the account, region, and model before the
IAM policy takes effect.

- Console → **Amazon Bedrock** → **Model access** → **Manage model access**
- Select the desired provider (e.g. Anthropic Claude family) and submit.
- Approval is typically automatic for standard providers but may take a few
  minutes.

Until approval is granted, `complete_text()` fails with the safe category
`model_access_denied`. The application will not silently reroute to another
provider.

---

## 4. Verification

After deployment, verify the AI wiring:

```bash
curl -s "$APP_URL/api/health" | python3 -c 'import sys,json; print(json.load(sys.stdin)["integrations"]["llm"])'
```

Expected values:

| Value            | Meaning                                                     |
|------------------|-------------------------------------------------------------|
| `bedrock`        | Enabled, configured, boto3 present. Ready for AI calls.     |
| `disabled`       | `AI_ENABLED=false`. AI is intentionally off.                |
| `misconfigured`  | `AI_PROVIDER` != `bedrock` or `BEDROCK_MODEL_ID` is empty.  |
| `unavailable`    | `boto3` is not installed. Deployment problem.               |

If the value is `bedrock`, exercise the SOAP or forms transcription route to
confirm the IAM role can invoke the model.

---

## 5. Safe logging

`llm_client.py` never logs:

- system prompts
- user prompts
- model responses
- patient names, DOBs, MRNs, addresses, phone numbers, emails
- SOAP-note content, lab values tied to identifiers
- AWS credentials or authorization headers

It logs only: internal request id, feature id (`session_id`), provider,
model id, latency, response character count, and a safe error category.

---

## 6. Not implemented / out of scope

- Streaming responses (`InvokeModelWithResponseStream`).
- WebSockets or long-running background AI workers.
- A general chat endpoint. Every AI feature must have a defined purpose,
  system prompt, permission set, and structured output validation. Future
  features should be added by defining a new `PromptTemplate` in
  `llm_client.py` and calling `run_template()` from the feature router.
