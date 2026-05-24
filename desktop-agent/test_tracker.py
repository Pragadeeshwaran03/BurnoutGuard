from tracker import ActivityTracker
import time
import mouse
import threading

def test_tracker():
    print("Starting tracker...")
    t = ActivityTracker(idle_threshold_seconds=120)
    t.start()
    
    # Simulate mouse events using the mouse library
    print("Simulating mouse moves, clicks, and scrolls...")
    mouse.move(1, 1, absolute=False)
    mouse.wheel(2) # 1 scroll event
    mouse.click('left') # 1 click event
    
    time.sleep(1.5)
    
    mouse.move(-1, -1, absolute=False)
    
    time.sleep(0.5)
    
    stats = t.get_and_reset()
    print("TEST STATS:", stats)
    
    t.stop()
    print("Done")

if __name__ == "__main__":
    test_tracker()
