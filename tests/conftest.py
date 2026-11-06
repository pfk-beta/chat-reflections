import os

# Must run before any test module imports chat_reflections.es, which reads these at import time.
# Otherwise ES tests would recreate and then delete the real `chat-*` indices.
os.environ["ES_PREFIX"] = "test-chat"
os.environ["CHAT_LANGUAGES"] = "polish,english"
