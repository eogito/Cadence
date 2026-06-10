# AI Task Scheduler

This project is an AI-powered task scheduler that connects to Gmail and Google Calendar. It extracts tasks from emails and schedules them with user approval.

## Features

- **Gmail Integration**: Read emails and extract tasks.
- **Email Summarization**: Summarize email content to identify tasks.
- **Task Extraction**: Automatically extract tasks from summarized emails.
- **Google Calendar Integration**: Read and write events to Google Calendar.
- **User Approval**: Get user approval before scheduling any tasks.

## Project Structure

```
ai-task-scheduler
├── src
│   ├── services
│   │   ├── ai_service.py        # Contains AiService for email summarization and task extraction
│   │   ├── calendar_service.py   # Contains CalendarService for Google Calendar operations
│   │   └── gmail_service.py      # Contains GmailService for reading emails
│   ├── models
│   │   └── task.py               # Defines the Task class
│   ├── config.py                 # Configuration settings for API keys and constants
│   └── main.py                   # Entry point of the application
├── .env.example                   # Example environment variables
├── requirements.txt               # Python dependencies
└── README.md                      # Project documentation
```

## Setup Instructions

1. Clone the repository:
   ```
   git clone <repository-url>
   cd ai-task-scheduler
   ```

2. Create a virtual environment:
   ```
   python -m venv venv
   source venv/bin/activate  # On Windows use `venv\Scripts\activate`
   ```

3. Install the required dependencies:
   ```
   pip install -r requirements.txt
   ```

4. Set up your environment variables:
   - Copy `.env.example` to `.env` and fill in your Gmail and Google Calendar API credentials.

5. Run the application:
   ```
   python src/main.py
   ```

## Usage

- The application will read your emails, summarize them, and extract tasks.
- You will be prompted to approve tasks before they are scheduled in your Google Calendar.

## Contributing

Feel free to submit issues or pull requests for improvements and new features.