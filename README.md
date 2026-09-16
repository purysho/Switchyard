<div align="center"><h1>Switchyard</h1><p><strong>A local developer workspace command center for projects, run configurations, processes, ports, notes, and release routines.</strong></p></div>

Switchyard is the flagship Purysho desktop project: a project-oriented local control surface that sits above individual tools. Register development folders, inspect their state, save run configurations, launch and stop processes, watch output, and see common local development ports at a glance.

## V1 capabilities
- Local project registry
- Project file/size snapshot
- Git branch and dirty-state detection
- Persistent notes per project
- Reusable run configurations
- Managed subprocess lifecycle with live logs
- Common localhost port probes
- Local JSON persistence in `~/.switchyard/`
- No account, hosted control plane, or telemetry

## Why it exists
Developer work tends to fragment across terminals, editors, scripts, task runners, port lists, and notes. Switchyard gives each local project one operational home without trying to replace those tools.

## Run
```powershell
pyw switchyard_desktop.pyw
```

## Tests
```powershell
python -m unittest discover -s tests -v
```

## Safety
Run configurations execute commands you explicitly save. Switchyard does not elevate privileges or execute discovered repository code automatically.

## License
MIT
