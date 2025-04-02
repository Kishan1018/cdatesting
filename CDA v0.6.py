from flask import Flask, request, jsonify
from flask_cors import CORS
from openai import OpenAI
import os
from uuid import uuid4
import re

app = Flask(__name__)
CORS(app)

client = OpenAI(api_key="sk-proj-UrgQXOqgKSchEjyuNru4T3BlbkFJHZcioI9C8npSCeALxNf7")

def get_markdown_files(directory):
    md_files = []
    if not os.path.exists(directory):
        return md_files
    for root, _, files in os.walk(directory):
        for file in files:
            if file.lower().endswith(".md"):
                md_files.append(os.path.join(root, file))
    return md_files

# Directories for file uploads.
directory_path_mobile = '/Users/kishanpatel/Library/CloudStorage/OneDrive-CHAMPSSoftwareInc/CDA/Official Training Files/Combined Mobile Training Files'
directory_path_desktop = '/Users/kishanpatel/Library/CloudStorage/OneDrive-CHAMPSSoftwareInc/CDA/Official Training Files/Combined Desktop Training Files'
directory_path_all_CHAMPS = '/Users/kishanpatel/Library/CloudStorage/OneDrive-CHAMPSSoftwareInc/CDA/Official Training Files/All Training Files (combined)'

# Global dictionaries for session-specific data.
session_threads = {}
session_histories = {}
session_support = {}         # Maps session_id to support choice ("mobile", "desktop", or "all")
session_assistants = {}      # Maps session_id to its assistant instance

# Global preloaded vector stores
global_vector_store_mobile = None
global_vector_store_desktop = None
global_vector_store_all = None

def preload_vector_stores():
    global global_vector_store_mobile, global_vector_store_desktop, global_vector_store_all

    # Preload Mobile vector store.
    mobile_file_paths = get_markdown_files(directory_path_mobile)
    global_vector_store_mobile = client.beta.vector_stores.create(name="CDA_Mobile")
    mobile_file_streams = [open(path, "rb") for path in mobile_file_paths]
    mobile_file_batch = client.beta.vector_stores.file_batches.upload_and_poll(
        vector_store_id=global_vector_store_mobile.id, files=mobile_file_streams
    )
    print("Mobile vector store status:", mobile_file_batch.status)
    print("Mobile file counts:", mobile_file_batch.file_counts)

    # Preload Desktop vector store.
    desktop_file_paths = get_markdown_files(directory_path_desktop)
    global_vector_store_desktop = client.beta.vector_stores.create(name="CDA_Desktop")
    desktop_file_streams = [open(path, "rb") for path in desktop_file_paths]
    desktop_file_batch = client.beta.vector_stores.file_batches.upload_and_poll(
        vector_store_id=global_vector_store_desktop.id, files=desktop_file_streams
    )
    print("Desktop vector store status:", desktop_file_batch.status)
    print("Desktop file counts:", desktop_file_batch.file_counts)

    # Preload All Training Files vector store.
    all_file_paths = get_markdown_files(directory_path_all_CHAMPS)
    global_vector_store_all = client.beta.vector_stores.create(name="CDA_All")
    all_file_streams = [open(path, "rb") for path in all_file_paths]
    all_file_batch = client.beta.vector_stores.file_batches.upload_and_poll(
        vector_store_id=global_vector_store_all.id, files=all_file_streams
    )
    print("All vector store status:", all_file_batch.status)
    print("All file counts:", all_file_batch.file_counts)

# Call the preload function when the application starts.
preload_vector_stores()

def extract_assistant_message(msg):
    try:
        if hasattr(msg, "role") and msg.role.lower() == "assistant":
            if hasattr(msg, "content"):
                content_val = msg.content
                if isinstance(content_val, list) and len(content_val) > 0:
                    first_item = content_val[0]
                    if hasattr(first_item, "text") and hasattr(first_item.text, "value"):
                        return first_item.text.value
                    else:
                        return str(first_item)
                elif isinstance(content_val, str):
                    return content_val
                else:
                    return str(content_val)
    except Exception:
        pass
    return None

def format_text(raw_text):
    """
    Replace text wrapped in double asterisks with HTML bold tags.
    For example, '**xxx**' becomes '<strong>xxx</strong>'.
    """
    formatted = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', raw_text)
    return formatted

@app.route('/chat', methods=['POST'])
def chat():
    try:
        user_input = request.json.get('message')
        session_id = request.json.get('session_id')
        support_choice = request.json.get('support_choice')  # May be "mobile", "desktop", or omitted

        if not session_id:
            session_id = str(uuid4())

        # If this is a new session, create session-specific assistant and thread.
        if session_id not in session_threads:
            # Determine support type; default to "all" if not mobile/desktop.
            if support_choice not in ['mobile', 'desktop']:
                support_choice = 'all'
            session_support[session_id] = support_choice

            # Use the preloaded vector store based on support choice.
            if support_choice == 'mobile':
                vector_store_id = global_vector_store_mobile.id
            elif support_choice == 'desktop':
                vector_store_id = global_vector_store_desktop.id
            else:
                vector_store_id = global_vector_store_all.id

            # Create a new assistant instance for this session.
            session_assistant = client.beta.assistants.create(
                name=f"CDA_{session_id}",
                instructions=(
                    "You are a chatbot for a software company called CHAMPS Software. Your job is to answer questions about the company's products for users in a clear, organized, and neat manner. Format your responses in plain text. For new topics within your answer, simply bold the topic text (using standard bold formatting) followed by a colon. Do not use any heading tags. Answer users' questions based on the files uploaded to you and ensure your grammar is correct. Remember, you 'work' for the company in question, CHAMPS Software. Never specify that you are or are not a human, but act as if you are one. Act as if you are a representative of the company. So, refer to apps and products as 'our', not 'their'. Not 'CHAMPS Products', say 'Our products'. Also be sure not to reference the details of your data training. You can say things like 'I am unable to answer that', but never something like 'That information is not in the referenced files'. You should never make references to the fact that you are trained on files, and should instead completely refrain from discussing your build information (software, model, training, etc.). Your information is in Markdown format. The documents contain text and pictures. The pictures are in the markdown, and will look like the following, for example: '![new.png](/.attachments/new-5c6d169e-6aec-49ac-9c08-1bdc430387c9.png =50x)'. Ignore the pictures and use only the text data to answer user queries."
                ),
                model="gpt-4o",
                tools=[{"type": "file_search"}],
            )
            # Update the assistant with the preloaded vector store.
            session_assistant = client.beta.assistants.update(
                assistant_id=session_assistant.id,
                tool_resources={"file_search": {"vector_store_ids": [vector_store_id]}},
            )
            session_assistants[session_id] = session_assistant

            # Create a new thread for this session.
            thread = client.beta.threads.create(
                tool_resources={"file_search": {"vector_store_ids": [vector_store_id]}},
                messages=[{"role": "user", "content": user_input}]
            )
            session_threads[session_id] = thread.id
            session_histories[session_id] = [{"role": "user", "content": user_input}]
        else:
            # Existing session: append the new user message.
            client.beta.threads.messages.create(
                thread_id=session_threads[session_id],
                role="user",
                content=user_input
            )
            session_histories[session_id].append({"role": "user", "content": user_input})

        # Use the session-specific assistant to run the thread.
        session_assistant = session_assistants[session_id]
        run = client.beta.threads.runs.create_and_poll(
            thread_id=session_threads[session_id],
            assistant_id=session_assistant.id
        )

        all_messages = list(client.beta.threads.messages.list(
            thread_id=session_threads[session_id],
            run_id=run.id
        ))

        assistant_message = None
        for msg in reversed(all_messages):
            assistant_message = extract_assistant_message(msg)
            if assistant_message:
                break

        if not assistant_message:
            assistant_message = "No response received."

        # Remove citation markers and use the raw text output.
        assistant_message = re.sub(r'【\d+:[^】]+】', '', assistant_message).strip()
        # Apply our custom formatting: Bold text wrapped in double asterisks.
        final_message = format_text(assistant_message)

        session_histories[session_id].append({"role": "assistant", "content": final_message})
        return jsonify({'reply': final_message, 'session_id': session_id})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/end_session', methods=['POST'])
def end_session():
    try:
        session_id = request.json.get('session_id')
        if session_id in session_threads:
            del session_threads[session_id]
            del session_histories[session_id]
            if session_id in session_support:
                del session_support[session_id]
            if session_id in session_assistants:
                del session_assistants[session_id]
        return jsonify({'status': 'session ended'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)