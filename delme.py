def toggle_pseudocal(*args):
  '''Toggle the pseudocalibration correction.'''
  if not args:
    return 'toggle'
  if len(args) == 1:
    if args[0] is True:
      return 'on'
    elif args[0] is False:
      return 'off'
    

print(toggle_pseudocal(False))