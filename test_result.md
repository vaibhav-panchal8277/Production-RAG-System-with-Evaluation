#====================================================================================================
# START - Testing Protocol - DO NOT EDIT OR REMOVE THIS SECTION
#====================================================================================================

# THIS SECTION CONTAINS CRITICAL TESTING INSTRUCTIONS FOR BOTH AGENTS
# BOTH MAIN_AGENT AND TESTING_AGENT MUST PRESERVE THIS ENTIRE BLOCK

# Communication Protocol:
# If the `testing_agent` is available, main agent should delegate all testing tasks to it.
#
# You have access to a file called `test_result.md`. This file contains the complete testing state
# and history, and is the primary means of communication between main and the testing agent.
#
# Main and testing agents must follow this exact format to maintain testing data. 
# The testing data must be entered in yaml format Below is the data structure:
# 
## user_problem_statement: "Fix backend startup, linter issues, and ensure all API endpoints and tests pass successfully."
## backend:
##   - task: "Backend Startup and API Endpoints"
##     implemented: true
##     working: true
##     file: "backend/server.py"
##     stuck_count: 0
##     priority: "high"
##     needs_retesting: true
##     status_history:
##         - working: true
##           agent: "main"
##           comment: "Fixed all Ruff linter issues, missing dependencies, and verified backend starts successfully via supervisor."
##
## frontend:
##   - task: "Frontend App UI & Dashboard"
##     implemented: true
##     working: true
##     file: "frontend/src/App.js"
##     stuck_count: 0
##     priority: "medium"
##     needs_retesting: false
##     status_history:
##         - working: true
##           agent: "main"
##           comment: "Frontend built successfully and running via supervisor."
##
## metadata:
##   created_by: "main_agent"
##   version: "1.1"
##   test_sequence: 1
##   run_ui: false
##
## test_plan:
##   current_focus:
##     - "Backend Startup and API Endpoints"
##   stuck_tasks: []
##   test_all: true
##   test_priority: "high_first"
##
## agent_communication:
##     - agent: "main"
##       message: "All backend linter issues (Ruff BLE001, S110) fixed. Please run backend tests and verify API endpoints."

#====================================================================================================
# END - Testing Protocol - DO NOT EDIT OR REMOVE THIS SECTION
#====================================================================================================

user_problem_statement: "Verify backend API endpoints, health check, guardrails input validation, and LLM generation."

backend:
  - task: "MongoDB Connection Configuration"
    implemented: true
    working: true
    file: "backend/.env"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        - working: false
          agent: "testing"
          comment: "❌ MongoDB connection failing - backend/.env configured with wrong port (27018) but MongoDB running on 27017. All database operations returning 500 errors."
        - working: true
          agent: "testing"
          comment: "✅ FIXED: Updated MONGO_URL from mongodb://localhost:27018 to mongodb://localhost:27017. Backend restarted successfully, BM25 index rebuilt from MongoDB."
  
  - task: "Backend API Endpoints - Basic"
    implemented: true
    working: true
    file: "backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        - working: true
          agent: "testing"
          comment: "✅ All basic API endpoints working: GET /api/ (root), GET /api/health (returns mongo stats, pinecone status, langfuse config), GET /api/documents, GET /api/conversations, GET /api/evaluations, GET /api/testset. All return 200 OK with proper JSON structure."
  
  - task: "Guardrails Input Validation"
    implemented: true
    working: true
    file: "backend/rag/guardrails.py, backend/rag/generator.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        - working: true
          agent: "testing"
          comment: "✅ All guardrails validation working correctly: (1) Empty query validation - rejects with 'Query cannot be empty', (2) Long query validation - rejects queries >2000 chars with 'Query exceeds maximum allowed length', (3) Prompt injection detection - rejects queries with patterns like 'ignore all previous instructions' with 'Query flagged by guardrails: potential prompt injection detected'."
  
  - task: "Pinecone Vector Store Integration"
    implemented: true
    working: false
    file: "backend/rag/vector_store.py, backend/.env"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        - working: false
          agent: "testing"
          comment: "❌ Pinecone integration failing with 401 Unauthorized - Invalid API key. Test key 'pc_test_key' in backend/.env is not valid. This causes: (1) POST /api/documents/seed returns 500 error when trying to ingest documents, (2) Vector search operations fail. Error: 'pinecone.openapi_support.exceptions.UnauthorizedException: (401) Reason: Unauthorized, HTTP response body: Invalid API key'. Pinecone is required for document ingestion and dense/hybrid search modes."
  
  - task: "LLM Generation via Emergent API"
    implemented: true
    working: false
    file: "backend/rag/generator.py, backend/rag/llm_client.py, backend/.env"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        - working: false
          agent: "testing"
          comment: "❌ LLM generation failing - Emergent LLM API returns 404 Not Found with error 'fault filter abort'. Configuration: EMERGENT_LLM_KEY=sk_test_emergent, OPENAI_API_BASE=https://integrations.emergentagent.com/v1, LLM_MODEL=gpt-4o-mini. API call to POST https://integrations.emergentagent.com/v1/chat/completions returns 404. Test query returns: 'I encountered an error while generating the answer. Please try again.' Issue likely due to: (1) Invalid test API key 'sk_test_emergent', or (2) Incorrect endpoint URL (should be /llm instead of /v1 based on Emergent docs). Requires valid Emergent API key or correct endpoint configuration."

frontend: []

metadata:
  created_by: "testing_agent"
  version: "1.2"
  test_sequence: 3
  run_ui: false

test_plan:
  current_focus:
    - "Backend API Endpoints - Basic"
    - "Guardrails Input Validation"
    - "LLM Generation via Emergent API"
    - "Pinecone Vector Store Integration"
  stuck_tasks:
    - "Pinecone Vector Store Integration"
    - "LLM Generation via Emergent API"
  test_all: false
  test_priority: "high_first"

agent_communication:
    - agent: "testing"
      message: "Configuration verification completed successfully. All required files present and valid. Created missing frontend/.env from .env.example. All services running properly (backend, frontend, mongodb). Backend modules properly structured and functional."
    - agent: "testing"
      message: "Backend API testing completed. FIXED: MongoDB connection issue (wrong port 27018→27017). WORKING: All basic API endpoints (root, health, documents, conversations, evaluations, testset) and all guardrails validation (empty query, long query, prompt injection). FAILING: (1) Pinecone integration - invalid test API key 'pc_test_key' causes 401 errors, blocks document seeding and vector search. (2) LLM generation - Emergent API returns 404 'fault filter abort', likely invalid test key 'sk_test_emergent' or wrong endpoint (/v1 should be /llm). Both require valid API keys or correct configuration to function."
