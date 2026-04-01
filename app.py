"""
app.py - Flask Web UI for the Controlled Execution Sandbox
===========================================================
Serves the HTML frontend and exposes a REST API endpoint for executing
Python code through the sandbox engine.

Run with: python app.py
or using a production WSGI server.
"""

from flask import Flask, render_template, request, jsonify
import logging
import main

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

app = Flask(__name__)

@app.route("/")
def index():
    """Serve the main UI page."""
    return render_template("index.html")

@app.route("/run", methods=["POST"])
def run_code():
    """
    API Endpoint to run untrusted code.
    Expects JSON: {"code": "print(1)"}
    """
    data = request.get_json()
    if not data or "code" not in data:
        return jsonify({
            "status": "error",
            "output": "",
            "reason": "Missing 'code' in request body"
        }), 400

    code = data["code"]
    try:
        result = main.run_sandbox(code)
        # Check for security alerts and pass them to frontend
        if "security_alert" in result:
            result["alert"] = result.pop("security_alert")
        return jsonify(result)
        
    except Exception as e:
        # Log full stack trace for debugging
        logger.exception("Unexpected error in run_code endpoint:")
        return jsonify({
            "status": "error",
            "output": "",
            "reason": "Internal server error (see logs for details)"
        }), 500

if __name__ == "__main__":
    print("Starting Sandbox UI Server on http://127.0.0.1:5000/")
    app.run(host="127.0.0.1", port=5000, debug=True)
