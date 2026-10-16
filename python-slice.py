history = [
    {"role": "model", "jawaban AI - 1": "test"},
    {"role": "user", "prompt dari user": "test"},
    {"role": "model", "jawaban AI - 2": "test"},
    {"role": "user", "prompt dari user 2": "test"},
]

MAX_TURNS = 1

print(MAX_TURNS * 2)

print(history[-(MAX_TURNS * 2) :])

h = list(range(25))

print(h[-10 * 2 :])

print(h)
