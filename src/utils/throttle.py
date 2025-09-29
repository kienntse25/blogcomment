import random, time
def human_pause(a: float, b: float) -> None:
    if a < 0: a = 0
    if b < a: b = a
    time.sleep(random.uniform(a, b))
