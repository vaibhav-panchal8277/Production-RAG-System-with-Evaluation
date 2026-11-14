# Deploying: Google Cloud Run (API) + Vercel (UI) + MongoDB Atlas

| Piece | Host | Cost for a demo |
| --- | --- | --- |
| FastAPI backend (`backend/Dockerfile`, unchanged) | Google Cloud Run | Free tier (a billing card must be on file) |
| React UI | Vercel | Free (Hobby) |
| Conversations, chunks, eval runs | MongoDB Atlas | Free (M0) |
| Vectors / LLM / tracing | Pinecone / Groq / Langfuse | your existing free accounts |

Nothing in the app code changes. Every setting below is an environment
variable or a console setting.

---

## 1. MongoDB Atlas (database)

1. Go to <https://cloud.mongodb.com> and create a free **M0** cluster. Pick a
   region near your Cloud Run region (this guide uses `europe-west1`).
2. **Database Access** → **Add user**. Click **Autogenerate Secure Password**
   (letters and digits only, so nothing needs URL-encoding), with role
   *Read and write to any database*. Never reuse the username as the password.
3. **Network Access** → **Add IP** → `0.0.0.0/0`. Cloud Run has no fixed
   outbound IP, so the strong password is what protects the database.
4. **Connect** → **Drivers** → copy the `mongodb+srv://USER:PASSWORD@…`
   string. This is `MONGO_URL`.

## 2. Backend on Google Cloud Run

1. Go to <https://console.cloud.google.com>, create a project (for example
   `rag-eval`), and link a billing account.
2. **Set a safety budget first.** Go to **Billing** → **Budgets & alerts** →
   create a budget of $1 with email alerts.
3. Store the secrets: **Secret Manager** → **Enable** → create one secret for
   each of these:

   | Secret name | Value |
   | --- | --- |
   | `GROQ_API_KEY` | your Groq key |
   | `PINECONE_API_KEY` | your Pinecone key |
   | `MONGO_URL` | the Atlas string from step 1 |
   | `RAG_API_KEY` | a random string: `python3 -c "import secrets; print(secrets.token_urlsafe(32))"` |
   | `LANGFUSE_SECRET_KEY` | optional |

4. **Cloud Run** → **Deploy container** → **Service** → **Continuously
   deploy from a repository (GitHub)** → **Set up with Cloud Build**:
   * Connect GitHub and choose `Production-RAG-System-with-Evaluation`,
     branch `^main$`.
   * Build type: **Dockerfile**. Source location: `/backend/Dockerfile`.
   * This creates the service and a Cloud Build trigger. The generated trigger
     can fail with `lstat /workspace/Dockerfile: no such file or directory`,
     because it builds from the repo root. Step 8 replaces its build config.
5. Service settings:

   | Setting | Value | Why |
   | --- | --- | --- |
   | Service name | `rag-eval-api` | |
   | Region | `europe-west1` | covered by the free tier (`us-central1` also works; change it in the step 9 YAML too) |
   | Authentication | **Allow unauthenticated invocations** | the browser calls it directly |
   | Billing | **Request-based** | free-tier friendly |
   | Min instances | `0` | scales to zero when idle |
   | **Max instances** | **`1`** | BM25, the ingest lock and eval jobs live in process memory, so there must be exactly one instance |
   | Container port | `8001` | the Dockerfile's uvicorn port |
   | Memory / CPU | `2 GiB` / `1` | MiniLM plus PyTorch idle at about 600 MB, and evals need headroom |
   | Request timeout | `900` seconds | room for a seed or a small eval |
   | Startup CPU boost | on | faster cold starts |

6. **Variables & Secrets**:
   * **Reference a secret** (exposed as an environment variable) for each
     secret from step 3, using the same names. When asked, grant the Cloud
     Run service account the *Secret Manager Secret Accessor* role.
   * Plain environment variables:

     ```
     DB_NAME=rag_eval
     LLM_MODEL=openai/gpt-oss-120b
     PINECONE_INDEX=rag-eval-index
     PINECONE_NAMESPACE=prod
     CORS_ORIGINS=https://placeholder.invalid      # replaced in section 4
     EVAL_CONCURRENCY=2
     EVAL_RAGAS_WORKERS=2
     LANGFUSE_PUBLIC_KEY=pk-lf-...                  # optional
     LANGFUSE_HOST=https://us.cloud.langfuse.com    # optional
     ```

7. Click **Create**.
8. **Grant the build permissions.** Builds run as the default compute service
   account (`<PROJECT_NUMBER>-compute@developer.gserviceaccount.com`). Without
   these roles a build fails in about a second with no logs. In **IAM** →
   that account → **Edit**, add:
   * Secret Manager Secret Accessor
   * Cloud Build Service Account
   * Cloud Run Admin
   * Service Account User
   * Logs Writer
9. **Fix the build trigger.** **Cloud Build** → **Triggers** → the trigger for
   this repo → **Edit** → Configuration: **Cloud Build configuration file** →
   Location: **Inline** → paste the YAML below → **Save** → **Run**. It
   builds `backend/`, pushes to Artifact Registry and rolls out a new
   revision on every push to `main`. Change `europe-west1` if you used
   another region.

   ```yaml
   steps:
     - id: Build
       name: gcr.io/cloud-builders/docker
       dir: backend
       args: [build, --no-cache, -t, europe-west1-docker.pkg.dev/$PROJECT_ID/cloud-run-source-deploy/rag-eval-api:$COMMIT_SHA, -f, Dockerfile, .]
     - id: Push
       name: gcr.io/cloud-builders/docker
       args: [push, europe-west1-docker.pkg.dev/$PROJECT_ID/cloud-run-source-deploy/rag-eval-api:$COMMIT_SHA]
     - id: Deploy
       name: gcr.io/google.com/cloudsdktool/cloud-sdk:slim
       entrypoint: gcloud
       args: [run, services, update, rag-eval-api, --platform=managed, --region=europe-west1, --image=europe-west1-docker.pkg.dev/$PROJECT_ID/cloud-run-source-deploy/rag-eval-api:$COMMIT_SHA, --quiet]
   timeout: 1800s
   options:
     logging: CLOUD_LOGGING_ONLY
   ```

   The `cloud-run-source-deploy` repository is created by step 4. If it is
   missing, create a Docker repository with that name in Artifact Registry
   in the same region.
10. The first build takes about 10 minutes. When it's done, copy the service
    URL (`https://rag-eval-api-….run.app`) and check:
    * `<URL>/api/` returns `{"service":"rag-eval","status":"ok"}`.
    * `<URL>/api/health` returns 200 with `mongo_docs` and `pinecone` info.
      A 500 here almost always means `MONGO_URL` is wrong.

## 3. Frontend on Vercel

1. Go to <https://vercel.com> → **Add New** → **Project** → import the repo.
2. **Root Directory**: `frontend`. Build settings come from
   [`frontend/vercel.json`](frontend/vercel.json).
3. **Environment Variables** (these are built into the bundle):

   | Name | Value |
   | --- | --- |
   | `REACT_APP_BACKEND_URL` | the Cloud Run URL, no trailing slash |
   | `REACT_APP_RAG_API_KEY` | the same value as the `RAG_API_KEY` secret |

   The key is needed because the backend requires it for `/query`. Anything in
   `REACT_APP_*` can be read by visitors in their browser, so treat this key
   as a demo key: rotate it after interviews (section 5).
4. Click **Deploy**, then copy the production URL (`https://….vercel.app`).

## 4. Connect them and seed the corpus

1. Cloud Run → `rag-eval-api` → **Edit & deploy new revision** → set
   `CORS_ORIGINS` to your exact Vercel production URL → **Deploy**.
2. Seed the sample corpus once. `read -s` keeps the key off the screen and
   out of shell history:

   ```bash
   API=https://rag-eval-api-xxxx.run.app
   read -rs KEY        # paste RAG_API_KEY, press Enter
   curl -sS -X POST "$API/api/documents/seed" -H "X-API-Key: $KEY" --max-time 900
   unset KEY
   ```

   Afterwards `<URL>/api/health` should show `mongo_docs: 4` and
   `bm25_chunks: 15`.

3. Open the Vercel URL and ask a question. The first one after an idle
   period can take 20–40 seconds (cold start).

## 5. Rotating the key

1. Secret Manager → `RAG_API_KEY` → **New version**.
2. Cloud Run → **Edit & deploy new revision** so the service picks up the new
   version.
3. Vercel → update `REACT_APP_RAG_API_KEY` → **Redeploy**.

## What to expect on the free tier

* **Cold start.** With zero instances when idle, the first visit after a quiet
  period takes about 20–40 seconds: the container starts, then the first
  question downloads and loads MiniLM. Requests after that are fast.
* **Evaluations.** On request-based billing, Cloud Run only gives the container
  CPU while a request is in flight. The UI polls a running eval every few
  seconds, so evals do progress, but slowly. Keep evals small (limit 3–5).
  Setting **Billing: instance-based** makes them run at full speed, but uses
  up free-tier credit faster. A full 45-question run can also exceed Groq's
  free daily token limit.
* **Previews.** CORS allows only the production Vercel URL, so Vercel preview
  deployments can't call the API. That's intended.
* **Data.** Atlas keeps conversations and eval history, and Pinecone keeps the
  vectors. The container itself is stateless; BM25 is rebuilt from Atlas on
  every start.

## Troubleshooting

| Symptom | Likely cause |
| --- | --- |
| Browser console shows a CORS error | `CORS_ORIGINS` doesn't exactly match the Vercel URL (check `https` and no trailing slash) |
| 401 on every question | `REACT_APP_RAG_API_KEY` differs from the secret, or Vercel wasn't redeployed after changing it |
| 503 or timeouts on first load | Cold start; wait about 30 seconds and retry |
| Revision fails to start | Check Cloud Run → **Logs**. Usually a missing secret or a wrong `MONGO_URL` |
| "Permission denied on secret" when deploying | The compute service account lacks *Secret Manager Secret Accessor* (section 2, step 8) |
| Build fails in about 1 second with no logs | The compute service account lacks the build roles (section 2, step 8) |
| `lstat /workspace/Dockerfile: no such file or directory` | The trigger builds from the repo root; use the inline YAML (section 2, step 9) |
| `/api/` works but `/api/health` returns 500 | Atlas rejects `MONGO_URL`: wrong password, or the user lacks read/write. Add a new secret version, then **Edit & deploy new revision** |
| Secret list says "No secrets found" | The secrets were created in a different project; check the project picker at the top of the console |
| Answers refuse everything | The corpus isn't seeded in this namespace; run the seed command |
