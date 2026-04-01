### 🚀 How to Use

#### Run Quick Tests (Recommended)
```bash
python test_simple.py
```
- Executes in ~2 seconds
- 13 essential tests
- All PASS ✓

#### Run Comprehensive Tests
```bash
python test_sandbox.py                    # With unittest
pytest test_sandbox.py -v                # With pytest
python -m unittest test_sandbox -v       # Specific tests
```

#### Test Sandbox Directly
```bash
python main.py --code "print(1 + 2)"     # Single code
python main.py --interactive              # Interactive mode
python main.py                            # Run attack simulations
```

#### Run Web Server
```bash
python app.py
# Visit: http://127.0.0.1:5000
```

---

### 📁 File Structure

```
sandbox/
├── main.py                      ✓ Simplified entry point
├── validator.py                 ✓ Simplified validation
├── executor.py                  ✓ Simplified execution
├── monitor.py                   ✓ Simplified monitoring
├── app.py                       ✓ Simplified Flask server
├── test_simple.py              ⭐ Quick tests (13 tests)
├── test_sandbox.py             ⭐ Comprehensive (26+ tests)
├── QUICK_START.md              📚 Usage guide
├── SIMPLIFICATION_SUMMARY.md   📚 Detailed changes
├── ARCHITECTURE.py             📚 Design diagrams
└── templates/, static/          Web UI files
```

### ✅ Verification Results

All tests passing:
```
VALIDATOR TESTS
✓ Valid arithmetic                  [PASS]
✓ Empty code blocked                [PASS]
✓ Import blocked                    [PASS]
✓ Eval blocked                      [PASS]
✓ Dunder attr blocked               [PASS]
✓ List comprehension                [PASS]

EXECUTOR TESTS
✓ Simple print                      [PASS]
✓ Math operation                    [PASS]
✓ Loop                              [PASS]
✓ Exception caught                  [PASS]

INTEGRATION TESTS
✓ Safe code                         [PASS]
✓ Import blocked                    [PASS]
✓ Multiple statements               [PASS]

ALL QUICK TESTS COMPLETED ✓
```

### 🛡️ Security Status

✓ All 8 security layers maintained:
1. ✓ AST validation (blocks dangerous constructs)
2. ✓ Import blocking (no module access)
3. ✓ Builtin restrictions (only ~40 safe functions)
4. ✓ Dunder attribute blocking (no sandbox escapes)
5. ✓ Resource limits (memory & CPU capped)
6. ✓ Timeout protection (infinite loop detection)
7. ✓ Output truncation (4KB limit, DOS prevention)
8. ✓ Audit logging (all executions logged)
---

*Last updated: April 1, 2026*
*All tests verified: ✓ PASSING*
