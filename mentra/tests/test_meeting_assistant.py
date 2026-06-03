import sys
import os
import time

# Ensure mentra path is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from mentra.workers.meeting_assistant_worker import MeetingAssistantWorker

def test():
    print("Testing MeetingAssistantWorker optimization...")
    worker = MeetingAssistantWorker()
    
    # Mock _generate_answer to avoid Ollama calls
    triggers = []
    def mock_generate_answer(question, transcript):
        print(f"-> TRIGGERED: \"{question}\"")
        triggers.append(question)
    worker._generate_answer = mock_generate_answer
    
    # 1. Initial trigger with a question
    print("\n--- Test 1: Initial Question ---")
    worker.analyze("What are the types of Machine Learning?")
    assert len(triggers) == 1, "Should have triggered once"
    assert triggers[-1] == "What are the types of Machine Learning?", "Should match question"
    
    # 2. Strict duplicate check (should ignore)
    print("\n--- Test 2: Strict Duplicate ---")
    worker.analyze("What are the types of Machine Learning?")
    assert len(triggers) == 1, "Should ignore exact duplicate"
    
    # 3. High similarity check (>90%) (should ignore)
    print("\n--- Test 3: High Similarity (>90%) ---")
    worker.analyze("What are the types of Machine Learning.") # Period instead of question mark
    worker.analyze("what are the types of machine learning?") # Lower case
    worker.analyze("  What are   the types of Machine Learning?  ") # Whitespaces
    assert len(triggers) == 1, "Should ignore highly similar questions (>90% similarity)"
    
    # 4. Genuinely new question check (should trigger, but respect cooldown first)
    print("\n--- Test 4: New Question on Cooldown ---")
    worker.analyze("How does deep learning work?")
    assert len(triggers) == 1, "Should respect cooldown (15s) and not trigger new question immediately"
    
    # 5. Let's bypass cooldown manually to verify it triggers once cooldown passes
    print("\n--- Test 5: New Question after Cooldown Bypass ---")
    worker.last_detection_time = 0.0 # Force cooldown bypass
    worker.analyze("How does deep learning work?")
    assert len(triggers) == 2, "Should trigger genuinely new question after cooldown"
    assert triggers[-1] == "How does deep learning work?", "Should match new question"
    
    # 6. Check duplicates for the new question
    print("\n--- Test 6: Duplicate of Second Question ---")
    worker.analyze("How does deep learning work?")
    assert len(triggers) == 2, "Should ignore duplicate of second question"
    
    print("\nAll MeetingAssistantWorker duplicate and similarity tests PASSED successfully!")

if __name__ == "__main__":
    test()
