# Test Proxy Plan

## Task
Test proxy `14.224.225.146:29087:ue56:ue56` to access URL:
- https://flowlinevalve.com/2022/09/ptfe-lined-ball-globe-valves-manufacturer-in-ahmedabad-gujarat-india/
- Verify if commenting works

## Files Created/Modified
- `test_proxy_debug.py` - New test script

## Test Script Details

### Proxy Configuration
- Proxy format: `IP:PORT:USER:PASS` → `http://ue56:ue56@14.224.225.146:29087`
- Uses Chrome driver with proxy support

### Test Steps
1. Create Chrome driver with proxy configuration
2. Navigate to target URL
3. Measure page load time
4. Check page title and content
5. Attempt to post a test comment

### Test Parameters
- HEADLESS mode: Based on config (default: True)
- Page load timeout: 25 seconds
- Find timeout: 8 seconds
- After submit pause: 2 seconds

## Running the Test

```bash
cd /Users/nguyenkien/workspace/blog-comment-tool
python test_proxy_debug.py
```

## Expected Output
- SUCCESS: Proxy working, page loads, comment posted
- FAILURE: Connection error, timeout, or comment form not found

## Logs
- Console output with progress
- Log file: `test_proxy_debug.log`

