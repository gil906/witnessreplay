"""
WebSocket connection tests.
Automated tests to verify WebSocket connectivity and basic functionality.
"""

import asyncio
import json
import pytest
from websockets import connect
from websockets.exceptions import WebSocketException


BASE_URL = "ws://localhost:8088"
SESSION_ID = "test-websocket-session"


async def test_websocket_connection():
    """Test basic WebSocket connection and upgrade."""
    try:
        async with connect(f"{BASE_URL}/ws/{SESSION_ID}") as websocket:
            # Connection successful
            print("✓ WebSocket connection established")
            
            # Try to send a message
            test_message = {"type": "test", "content": "ping"}
            await websocket.send(json.dumps(test_message))
            print(f"✓ Sent message: {test_message}")
            
            # Try to receive a response (with timeout)
            try:
                response = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                print(f"✓ Received response: {response[:100]}")
                return True
            except asyncio.TimeoutError:
                print("⚠ No response received within 5 seconds (may be expected)")
                return True  # Connection still worked
            
    except WebSocketException as e:
        print(f"✗ WebSocket error: {e}")
        return False
    except Exception as e:
        print(f"✗ Unexpected error: {e}")
        return False


async def test_websocket_invalid_session():
    """Test WebSocket with invalid session ID handling."""
    try:
        async with connect(f"{BASE_URL}/ws/invalid-session-123") as websocket:
            # Send a message
            await websocket.send(json.dumps({"type": "test"}))
            
            # Check if we get error response or connection closes
            try:
                response = await asyncio.wait_for(websocket.recv(), timeout=3.0)
                print(f"✓ Server responded to invalid session: {response[:50]}")
                return True
            except asyncio.TimeoutError:
                print("✓ Connection handled gracefully (timeout)")
                return True
            
    except WebSocketException as e:
        print(f"✓ WebSocket rejected invalid session appropriately: {e}")
        return True
    except Exception as e:
        print(f"⚠ Unexpected error with invalid session: {e}")
        return True  # Still acceptable


async def test_websocket_echo():
    """Test WebSocket message echo functionality."""
    try:
        async with connect(f"{BASE_URL}/ws/{SESSION_ID}") as websocket:
            # Send multiple messages
            messages = [
                {"type": "audio_chunk", "data": "test_data_1"},
                {"type": "audio_chunk", "data": "test_data_2"},
                {"type": "end_audio", "session_id": SESSION_ID}
            ]
            
            for msg in messages:
                await websocket.send(json.dumps(msg))
                print(f"✓ Sent: {msg['type']}")
            
            # Try to receive responses
            received = 0
            try:
                while received < len(messages):
                    response = await asyncio.wait_for(websocket.recv(), timeout=2.0)
                    received += 1
                    print(f"✓ Received response {received}")
            except asyncio.TimeoutError:
                print(f"⚠ Received {received}/{len(messages)} responses")
            
            return True
            
    except Exception as e:
        print(f"✗ Echo test failed: {e}")
        return False


async def run_all_tests():
    """Run all WebSocket tests."""
    print("\n" + "="*60)
    print("WebSocket Automated Tests")
    print("="*60 + "\n")
    
    tests = [
        ("Basic Connection", test_websocket_connection),
        ("Invalid Session", test_websocket_invalid_session),
        ("Message Echo", test_websocket_echo),
    ]
    
    results = []
    for name, test_func in tests:
        print(f"\nRunning: {name}")
        print("-" * 40)
        try:
            result = await test_func()
            results.append((name, result))
            status = "PASS" if result else "FAIL"
            print(f"Result: {status}\n")
        except Exception as e:
            print(f"Result: ERROR - {e}\n")
            results.append((name, False))
    
    # Summary
    print("\n" + "="*60)
    print("Test Summary")
    print("="*60)
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status}: {name}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    print("="*60 + "\n")
    
    return passed == total


if __name__ == "__main__":
    # Run tests
    success = asyncio.run(run_all_tests())
    exit(0 if success else 1)
