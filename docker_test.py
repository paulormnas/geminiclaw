import docker
print('Importing docker...')
client = docker.from_env()
print('Docker client created!')
client.ping()
print('Docker ping successful!')
