// Elements
const editor = document.getElementById('code-editor');
const output = document.getElementById('output');
const errorBox = document.getElementById('error-box');
const runBtn = document.getElementById('run-btn');
const clearBtn = document.getElementById('clear-btn');
const statusBadge = document.getElementById('status');
const timing = document.getElementById('timing');

// Handle Run
runBtn.addEventListener('click', async () => {
    const code = editor.value.trim();
    if (!code) return;

    // Reset UI
    setLoading(true);
    output.textContent = "Executing...";
    errorBox.classList.add('hidden');
    timing.textContent = "";

    try {
        const res = await fetch('/run', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ code })
        });

        const data = await res.json();
        renderResult(data);
    } catch (err) {
        renderResult({
            status: 'error',
            output: '',
            reason: 'Network Error: Backend is unreachable.'
        });
    } finally {
        setLoading(false);
    }
});

// Handle Clear
clearBtn.addEventListener('click', () => {
    output.textContent = "Output will appear here...";
    errorBox.classList.add('hidden');
    statusBadge.className = "status-ready";
    statusBadge.textContent = "Ready";
    timing.textContent = "";
});

function setLoading(isLoading) {
    runBtn.disabled = isLoading;
    runBtn.textContent = isLoading ? "Running..." : "Run Code";
    if (isLoading) {
        statusBadge.className = "status-running";
        statusBadge.textContent = "Running";
    }
}

function renderResult(data) {
    const { status, output: stdout, reason, execution_time_ms } = data;

    // 1. Status
    statusBadge.textContent = status.toUpperCase();
    statusBadge.className = `status-${status}`;

    // 2. Output
    output.textContent = stdout || (status === 'allowed' ? '(No output)' : '');
    output.style.color = (status === 'allowed') ? '#e6edf3' : '#8b949e';

    // 3. Error/Reason
    if (reason && status !== 'allowed') {
        errorBox.textContent = reason;
        errorBox.classList.remove('hidden');
    } else {
        errorBox.classList.add('hidden');
    }

    // 4. Timing
    if (execution_time_ms !== undefined) {
        timing.textContent = `${execution_time_ms}ms`;
    }
}

// Allow Tab key in textarea
editor.addEventListener('keydown', (e) => {
    if (e.key === 'Tab') {
        e.preventDefault();
        const start = editor.selectionStart;
        const end = editor.selectionEnd;
        editor.value = editor.value.substring(0, start) + "    " + editor.value.substring(end);
        editor.selectionStart = editor.selectionEnd = start + 4;
    }
});
