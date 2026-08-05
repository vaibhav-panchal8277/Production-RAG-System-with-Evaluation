"""Backend API Tests for RAG Evaluation System"""
import os
import requests
from dotenv import load_dotenv

# Load environment variables
load_dotenv("/app/backend/.env")

# Get backend URL from environment
BACKEND_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001")
API_BASE = f"{BACKEND_URL}/api"

def test_health_endpoint():
    """Test GET /api/health returns 200 and langfuse_configured is true"""
    print(f"\n{'='*60}")
    print("Testing GET /api/health")
    print(f"{'='*60}")
    
    try:
        response = requests.get(f"{API_BASE}/health", timeout=10)
        
        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.json()}")
        
        # Check status code
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        # Check response structure
        data = response.json()
        assert "langfuse_configured" in data, "langfuse_configured field missing"
        
        # Check langfuse_configured is true
        assert data["langfuse_configured"] is True, f"Expected langfuse_configured=True, got {data['langfuse_configured']}"
        
        print("\n✅ PASS: Health endpoint returns 200 and langfuse_configured is True")
        return True
        
    except requests.exceptions.RequestException as e:
        print(f"\n❌ FAIL: Request failed - {e}")
        return False
    except AssertionError as e:
        print(f"\n❌ FAIL: {e}")
        return False
    except Exception as e:
        print(f"\n❌ FAIL: Unexpected error - {e}")
        return False

if __name__ == "__main__":
    print(f"Backend URL: {BACKEND_URL}")
    print(f"API Base: {API_BASE}")
    
    success = test_health_endpoint()
    
    if success:
        print("\n" + "="*60)
        print("ALL TESTS PASSED ✅")
        print("="*60)
        exit(0)
    else:
        print("\n" + "="*60)
        print("TESTS FAILED ❌")
        print("="*60)
        exit(1)
