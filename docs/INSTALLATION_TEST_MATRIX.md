# Installation verification matrix

| Platform | Automated gate | Coverage | Remaining manual gate |
|---|---|---|---|
| Windows | Windows GitHub runner | PowerShell parsing, CMD entry, isolated installation, MCP registration, local verification | Dedicated Chrome login and real ChatGPT Web return |
| Linux | Docker build | User-level installation, dependency setup, Profile creation, MCP configuration, doctor | Desktop Chrome login and real ChatGPT Web return |
| macOS | macOS GitHub runner | Non-GUI installation with simulated Chrome binary, Profile creation, MCP configuration, doctor | Real Chrome GUI login and real ChatGPT Web return |

No platform is marked fully delivered until its manual gate succeeds on a real user device.
