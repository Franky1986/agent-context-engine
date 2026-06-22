from __future__ import annotations

from .version import MONITOR_VERSION


MONITOR_HTML = f"""<!doctype html>
<html lang="__DEFAULT_MONITOR_LANG__">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Agent Context Engine Monitor {MONITOR_VERSION}</title>
  <style>
    :root {{ color: #18212f; background: #f4efe7; font-family: ui-sans-serif, system-ui, sans-serif; }}
    body {{ margin: 0; min-height: 100vh; display: grid; place-items: center; }}
    main {{ max-width: 720px; border: 1px solid rgba(24, 33, 47, 0.14); border-radius: 28px; background: rgba(255, 252, 246, 0.86); box-shadow: 0 24px 80px rgba(45, 51, 64, 0.12); padding: 36px; }}
    h1 {{ margin: 0 0 12px; font-size: clamp(2rem, 6vw, 4rem); line-height: 0.95; }}
    p {{ color: #657285; font-size: 1.05rem; line-height: 1.6; }}
    code {{ background: rgba(24, 33, 47, 0.08); border-radius: 8px; padding: 2px 6px; }}
  </style>
</head>
<body>
  <main>
    <p>Agent Context Engine Monitor {MONITOR_VERSION}</p>
    <h1>React monitor build missing.</h1>
    <p>The Python monitor now serves the React app from <code>frontend/dist</code>. Run the frontend build and restart the monitor, or use Vite during development.</p>
  </main>
  <script></script>
</body>
</html>"""
