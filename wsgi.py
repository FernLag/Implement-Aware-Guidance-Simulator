"""Entry point.

    python3 wsgi.py                 development server on port 5000
    gunicorn -w 4 wsgi:app          production, behind a TLS terminator
"""

from web.app import create_app

app = create_app()

if __name__ == "__main__":
    import os
    app.run(
        host=os.environ.get("AGGSIM_HOST", "127.0.0.1"),
        port=int(os.environ.get("AGGSIM_PORT", "5000")),
        debug=app.settings.debug,
    )
