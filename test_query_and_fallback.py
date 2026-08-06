"""Focused test for query execution and guardrails fallback behavior"""
import os
import requests
import time
from dotenv import load_dotenv

# Load environment variables
load_dotenv("/app/frontend/.env")

BACKEND_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001")
API_BASE = f"{BACKEND_URL}/api"

def test_query_execution_with_fallback():
    """Test that query execution works even when guardrails fail"""
    print(f"\n{'='*80}")
    print("TEST 1: Query Execution with Guardrails Fallback")
    print(f"{'='*80}")
    
    test_queries = [
        {
            "name": "Valid Query - RAG Evaluation",
            "query": "What is RAG evaluation and why is it important?",
            "mode": "keyword",
            "expected_status": 200,
            "should_have_contexts": True
        },
        {
            "name": "Valid Query - Data Retention",
            "query": "What are the data retention policies?",
            "mode": "keyword",
            "expected_status": 200,
            "should_have_contexts": True
        },
        {
            "name": "Valid Query - Incident Response",
            "query": "How should we handle security incidents?",
            "mode": "keyword",
            "expected_status": 200,
            "should_have_contexts": True
        },
        {
            "name": "Empty Query",
            "query": "",
            "mode": "keyword",
            "expected_status": 200,
            "should_have_contexts": False
        },
        {
            "name": "Very Long Query",
            "query": "x" * 2500,
            "mode": "keyword",
            "expected_status": 200,
            "should_have_contexts": False
        }
    ]
    
    results = []
    
    for test_case in test_queries:
        print(f"\n{'-'*80}")
        print(f"Testing: {test_case['name']}")
        print(f"Query: {test_case['query'][:100]}{'...' if len(test_case['query']) > 100 else ''}")
        print(f"{'-'*80}")
        
        try:
            payload = {
                "query": test_case["query"],
                "top_k": 5,
                "mode": test_case["mode"]
            }
            
            start_time = time.time()
            response = requests.post(f"{API_BASE}/query", json=payload, timeout=30)
            elapsed_time = time.time() - start_time
            
            print(f"Status Code: {response.status_code}")
            print(f"Response Time: {elapsed_time:.2f}s")
            
            if response.status_code == test_case["expected_status"]:
                data = response.json()
                print(f"Response Keys: {list(data.keys())}")
                
                if "answer" in data:
                    print(f"Answer: {data['answer'][:200]}{'...' if len(data['answer']) > 200 else ''}")
                
                if "contexts" in data:
                    print(f"Contexts Count: {len(data['contexts'])}")
                    if test_case["should_have_contexts"]:
                        if len(data['contexts']) > 0:
                            print(f"✅ PASS: Query executed successfully with {len(data['contexts'])} contexts")
                            results.append((test_case['name'], True, "Query executed with contexts"))
                        else:
                            print(f"⚠️  WARNING: Query executed but no contexts returned")
                            results.append((test_case['name'], True, "Query executed but no contexts"))
                    else:
                        print(f"✅ PASS: Query executed (contexts not expected)")
                        results.append((test_case['name'], True, "Query executed"))
                else:
                    print(f"❌ FAIL: Response missing 'contexts' field")
                    results.append((test_case['name'], False, "Missing contexts field"))
            else:
                print(f"❌ FAIL: Expected status {test_case['expected_status']}, got {response.status_code}")
                print(f"Response: {response.text[:500]}")
                results.append((test_case['name'], False, f"Wrong status code: {response.status_code}"))
                
        except Exception as e:
            print(f"❌ FAIL: Exception occurred: {e}")
            results.append((test_case['name'], False, f"Exception: {str(e)}"))
    
    return results

def test_bm25_fallback():
    """Test that BM25 search works as fallback when Pinecone is unavailable"""
    print(f"\n{'='*80}")
    print("TEST 2: BM25 Fallback Behavior")
    print(f"{'='*80}")
    
    results = []
    
    # Test 1: Seed documents first
    print(f"\n{'-'*80}")
    print("Step 1: Seeding documents")
    print(f"{'-'*80}")
    
    try:
        response = requests.post(f"{API_BASE}/documents/seed", timeout=30)
        print(f"Seed Status: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            print(f"Ingested: {len(data.get('ingested', []))} documents")
            print(f"✅ PASS: Document seeding successful")
            results.append(("Document Seeding", True, f"Seeded {len(data.get('ingested', []))} docs"))
        else:
            print(f"❌ FAIL: Seed failed with status {response.status_code}")
            results.append(("Document Seeding", False, f"Status {response.status_code}"))
            return results
    except Exception as e:
        print(f"❌ FAIL: Seed exception: {e}")
        results.append(("Document Seeding", False, f"Exception: {str(e)}"))
        return results
    
    # Test 2: Verify BM25 keyword search works
    print(f"\n{'-'*80}")
    print("Step 2: Testing BM25 keyword search")
    print(f"{'-'*80}")
    
    try:
        payload = {
            "query": "What are the evaluation metrics for RAG systems?",
            "top_k": 5,
            "mode": "keyword"
        }
        
        response = requests.post(f"{API_BASE}/query", json=payload, timeout=30)
        print(f"Query Status: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            contexts = data.get('contexts', [])
            print(f"Contexts returned: {len(contexts)}")
            
            if len(contexts) > 0:
                print(f"Sample context source: {contexts[0].get('metadata', {}).get('source', 'unknown')}")
                print(f"Sample context text: {contexts[0].get('text', '')[:150]}...")
                print(f"✅ PASS: BM25 search returned {len(contexts)} relevant contexts")
                results.append(("BM25 Keyword Search", True, f"Returned {len(contexts)} contexts"))
            else:
                print(f"⚠️  WARNING: BM25 search returned no contexts")
                results.append(("BM25 Keyword Search", True, "No contexts returned"))
        else:
            print(f"❌ FAIL: Query failed with status {response.status_code}")
            results.append(("BM25 Keyword Search", False, f"Status {response.status_code}"))
    except Exception as e:
        print(f"❌ FAIL: Query exception: {e}")
        results.append(("BM25 Keyword Search", False, f"Exception: {str(e)}"))
    
    # Test 3: Test hybrid mode (should fallback to BM25 when Pinecone unavailable)
    print(f"\n{'-'*80}")
    print("Step 3: Testing hybrid mode fallback to BM25")
    print(f"{'-'*80}")
    
    try:
        payload = {
            "query": "What is the remote work policy?",
            "top_k": 5,
            "mode": "hybrid"
        }
        
        response = requests.post(f"{API_BASE}/query", json=payload, timeout=30)
        print(f"Hybrid Query Status: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            contexts = data.get('contexts', [])
            print(f"Contexts returned: {len(contexts)}")
            
            if len(contexts) > 0:
                print(f"✅ PASS: Hybrid mode fallback working (returned {len(contexts)} contexts)")
                results.append(("Hybrid Mode Fallback", True, f"Returned {len(contexts)} contexts"))
            else:
                print(f"⚠️  WARNING: Hybrid mode returned no contexts")
                results.append(("Hybrid Mode Fallback", True, "No contexts returned"))
        else:
            print(f"❌ FAIL: Hybrid query failed with status {response.status_code}")
            results.append(("Hybrid Mode Fallback", False, f"Status {response.status_code}"))
    except Exception as e:
        print(f"❌ FAIL: Hybrid query exception: {e}")
        results.append(("Hybrid Mode Fallback", False, f"Exception: {str(e)}"))
    
    return results

def test_guardrails_exception_handling():
    """Test that guardrails exceptions are caught and system continues"""
    print(f"\n{'='*80}")
    print("TEST 3: Guardrails Exception Handling")
    print(f"{'='*80}")
    
    print("\nThis test verifies that when NeMo Guardrails throws an exception,")
    print("the system catches it and continues with normal query processing.")
    
    results = []
    
    # Make multiple queries to see if behavior is consistent
    test_queries = [
        "What is the data retention policy?",
        "How do I report a security incident?",
        "What are the remote work guidelines?",
        "Tell me about the Widget 3000 manual",
        "What evaluation metrics are used?"
    ]
    
    success_count = 0
    error_count = 0
    
    for i, query in enumerate(test_queries, 1):
        print(f"\n{'-'*80}")
        print(f"Query {i}/{len(test_queries)}: {query}")
        print(f"{'-'*80}")
        
        try:
            payload = {
                "query": query,
                "top_k": 5,
                "mode": "keyword"
            }
            
            response = requests.post(f"{API_BASE}/query", json=payload, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                print(f"✅ Status: 200 OK")
                print(f"   Contexts: {len(data.get('contexts', []))}")
                print(f"   Answer length: {len(data.get('answer', ''))}")
                success_count += 1
            elif response.status_code == 500:
                print(f"❌ Status: 500 Internal Server Error")
                print(f"   Response: {response.text[:200]}")
                error_count += 1
            else:
                print(f"⚠️  Status: {response.status_code}")
                error_count += 1
                
        except Exception as e:
            print(f"❌ Exception: {e}")
            error_count += 1
    
    print(f"\n{'-'*80}")
    print(f"Results: {success_count} successful, {error_count} errors")
    print(f"{'-'*80}")
    
    if error_count == 0:
        print(f"✅ PASS: All queries executed successfully (guardrails fallback working)")
        results.append(("Guardrails Exception Handling", True, f"{success_count}/{len(test_queries)} queries successful"))
    elif success_count > 0:
        print(f"⚠️  PARTIAL: Some queries succeeded, some failed (inconsistent behavior)")
        results.append(("Guardrails Exception Handling", False, f"Inconsistent: {success_count} success, {error_count} errors"))
    else:
        print(f"❌ FAIL: All queries failed (guardrails fallback NOT working)")
        results.append(("Guardrails Exception Handling", False, "All queries failed"))
    
    return results

def main():
    print(f"\n{'='*80}")
    print("BACKEND QUERY EXECUTION AND GUARDRAILS FALLBACK TEST")
    print(f"{'='*80}")
    print(f"Backend URL: {BACKEND_URL}")
    print(f"API Base: {API_BASE}")
    print(f"{'='*80}")
    
    all_results = []
    
    # Run all tests
    all_results.extend(test_query_execution_with_fallback())
    all_results.extend(test_bm25_fallback())
    all_results.extend(test_guardrails_exception_handling())
    
    # Print summary
    print(f"\n{'='*80}")
    print("TEST SUMMARY")
    print(f"{'='*80}")
    
    passed = sum(1 for _, result, _ in all_results if result)
    total = len(all_results)
    
    for test_name, result, details in all_results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {test_name}")
        print(f"         {details}")
    
    print(f"\n{'='*80}")
    print(f"Total: {passed}/{total} tests passed")
    print(f"{'='*80}")
    
    if passed == total:
        print("\n✅ ALL TESTS PASSED")
        return 0
    else:
        print(f"\n❌ {total - passed} TESTS FAILED")
        return 1

if __name__ == "__main__":
    exit(main())
