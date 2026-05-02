print('Starting db import...')
from src.db import get_pool
print('Pool import successful!')
pool = get_pool()
print('Pool object created!')
# pool.open() # Let's see if it hangs here
print('Success!')
q