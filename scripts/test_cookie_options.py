import httpx

def test_request(name, cookies):
    url = "https://arcadia-roster.up.railway.app/api/clip/campaigns"
    headers = {
        "Referer": "https://arcadia-roster.up.railway.app/clip/campaigns",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"
    }
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(url, headers=headers, cookies=cookies)
            print(f"[{name}] Status: {resp.status_code}, Length: {len(resp.text)}")
            if resp.status_code == 200:
                print(f"[{name}] Success! Keys in response: {list(resp.json().keys()) if isinstance(resp.json(), dict) else resp.json()}")
            else:
                print(f"[{name}] Error: {resp.text[:200]}")
    except Exception as e:
        print(f"[{name}] Failed: {e}")

session_token = "eyJhbGciOiJkaXIiLCJlbmMiOiJBMjU2R0NNIn0..w1P8vhNlWbyqxFY6.-j1JDJw5B-wg0nDDKT92bs3Cibs1nmq66ffoQcRMTFwx3rrQ3gnt9jRe9OBKTj8DZAFmAC3_kNK5jMd2G-W3wfmBcbA-lbxqKvOeKmocQanUBtz341Q5El-qLlCYvTJ4ibA39DeaNYXMGtgUo8k28DbRMmMCp1eoCL6Ur6O2KSXl0sMX3PfFOcdCFGZqJV8Cwy5_Z6JGX75Iw28Dgqy7PGQo6As5rjxseoImqSkOL9kQEaWdVgl8m9WLAreGDoUFdJnegWG0d_Hb_yfnLbIjrp2EP2pBPaJ7_zqtYDOTQ5OE9oCvXoaBOGu7KyEOtkhDDlqDVgbwsjMvNxErqg.NsCVRKOP4mfVbfWIdPWf0g"

# 1. No cookies
test_request("NO COOKIES", {})

# 2. Only session token
test_request("ONLY SESSION TOKEN", {"__Secure-next-auth.session-token": session_token})

# 3. Session token with fake csrf/callback
test_request("SESSION TOKEN WITH FAKE COOKIES", {
    "__Host-next-auth.csrf-token": "abc",
    "__Secure-next-auth.callback-url": "abc",
    "__Secure-next-auth.session-token": session_token
})
