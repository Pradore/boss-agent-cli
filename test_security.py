import json

# Test case 1: malicious geek_id with quotes attempting XSS
geek_id_xss = 'abc"]; alert(1); //'
args_json = json.dumps({'geekId': geek_id_xss, 'buttonText': '打招呼'})
print('=== Test 1: XSS attempt ===')
print(f'geek_id: {repr(geek_id_xss)}')
print(f'args_json: {args_json}')
print(f'expression: (script)({args_json})')
print()

# What happens inside JS
print('Inside JS after JSON.parse:')
deserialized = json.loads(args_json)
print(f'  args.geekId = {repr(deserialized["geekId"])}')
print()

# The actual querySelector call
print('The querySelector would be:')
print(f'  doc.querySelector(\'[data-geekid="{deserialized["geekId"]}"]\' )')
print()

# Test case 2: Does the selector actually break?
print('=== Test 2: Selector injection ===')
geek_id_selector = 'abc"][onclick="alert(1)"][data-x="'
args_json2 = json.dumps({'geekId': geek_id_selector, 'buttonText': '打招呼'})
deserialized2 = json.loads(args_json2)
print(f'geek_id: {repr(geek_id_selector)}')
print(f'The querySelector would be:')
print(f'  doc.querySelector(\'[data-geekid="{deserialized2["geekId"]}"]\' )')
print()
print('This creates selector: [data-geekid="abc"][onclick="alert(1)"][data-x=""]')
print('Result: querySelector would find elements with data-geekid="abc" (incorrect match!)')
