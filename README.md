Easy-Anki

📖 Lightweight web tool for building and managing Anki-style flashcards directly from your browser, complete with simple progress 
tracking and session logging.

🌐 Live Demo: https://jassk0-github-io.onrender.com/

📖 Overview

Easy-Anki is a lightweight Flask-based web application designed to simplify the creation and management of Anki-style flashcards through a clean,
browser-based interface. Rather than manually adding cards in the native Anki desktop app, users can:

• Add question–answer cards quickly in a web interface
• Import data from CSV files
• Track study progress and sessions over time
• Organize decks without dealing with Anki’s editor

The project focuses on a minimal setup, ease of use, and an intuitive workflow.

✨ Features

• Web-based card creation from any device
• CSV support for loading large question banks
• Persistent study and session logs stored locally
• Deployment-ready architecture optimized for Render
• No installation required when using the hosted version


🛠️ Usage

Option 1: Use the hosted version
Visit the following link and start adding cards immediately:
https://jassk0-github-io.onrender.com/

Option 2: Run locally
Clone the repository, install the dependencies listed in requirements.txt, and run the Flask application. After launching,
open a browser and go to localhost on port 5000.

📦 Technologies

Backend: Python and Flask
Frontend: HTML, CSS, Jinja2 templates
Storage: JSON and JSONL logs
Deployment: Render using WSGI and Procfile

🔧 Configuration

All progress and session data is currently stored in JSON and JSONL files. No external database is required.

Known Limitation:
Session data is not reliably persistent because the application does not use an actual database. Data may
reset when deployed or restarted.

Planned Improvement:
Introduce SQLite for local development and PostgreSQL for production deployments to ensure persistent session tracking.

🤝 Contributing

Contributions are welcome. Possible improvements include:

• Adding a proper database backend
• Exporting decks into native Anki formats such as .apkg
• Improving the user interface and adding feedback messages
• Adding tests for routes, data functions, and import logic

To contribute, fork the repo, create a feature branch, commit changes, and open a pull request.

📝 Changelog

Initial commit: project structure created
app.py implemented: core Flask functionality added
Leaderboard and answering bug fixed
Deployment configuration improved with wsgi.py and Procfile

There are no releases or tags at this time.

❤️ Acknowledgements

This project is inspired by Anki and the spaced-repetition learning model.
Developed and maintained by Jass Kahlon (GitHub: @JassK0)

🔧 Things to Fix / Improve

• Session persistence bug due to lack of a real database
• Add screenshots and examples of deck import workflows
• Improve error handling for malformed CSV or missing fields

Enjoy studying smarter, not harder 🎓
Start using Easy-Anki today: https://jassk0-github-io.onrender.com/
