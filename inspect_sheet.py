import urllib.request
url = 'https://docs.google.com/spreadsheets/d/1QJ7wotWFoNNSwzIIIAGRcf4WAaYz1pXjhljYSk5h9DI/export?format=csv&gid=0'
with urllib.request.urlopen(url, timeout=30) as resp:
    data = resp.read().decode('utf-8-sig')
print(data[:8000])
