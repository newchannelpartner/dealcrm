with open('index.html', 'r') as f:
    content = f.read()

# Change the value from '' to 'none' for the standalone option
old = '<option value="">None (standalone)</option>'
new = '<option value="none">None (standalone)</option>'
if old in content:
    content = content.replace(old, new)
    print('Changed standalone value to "none"')

    # Update saveNote - remove || 'none' fallback since value is now 'none'
    old2 = "var entityType = document.getElementById('noteEntityType').value || 'none';"
    new2 = "var entityType = document.getElementById('noteEntityType').value;"
    if old2 in content:
        content = content.replace(old2, new2)
        print('Updated saveNote entityType (no fallback needed)')
    else:
        print('saveNote fallback pattern not found')

    # Update loadNoteEntities type check
    old3 = "(type === '') ? 'none' : 'inline-block'"
    new3 = "(type === 'none') ? 'none' : 'inline-block'"
    if old3 in content:
        content = content.replace(old3, new3)
        print('Updated loadNoteEntities display check')

    old4 = "if (!type) return;"
    new4 = "if (type === 'none') return;"
    if old4 in content:
        content = content.replace(old4, new4)
        print('Updated loadNoteEntities return condition')
    else:
        print('loadNoteEntities return pattern not found')

    with open('index.html', 'w') as f:
        f.write(content)
    print('Written.')
else:
    print('Pattern not found - checking...')
    for i, line in enumerate(content.split('\n'), 1):
        if 'None (standalone)' in line:
            print(f'  Line {i}: {line.strip()}')
