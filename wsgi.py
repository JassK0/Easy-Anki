from webgui import app

# WSGI entrypoint for gunicorn or other WSGI servers
# Example: gunicorn wsgi:app -b 0.0.0.0:8000

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)
