# Judge-ready demo packages

Create a secret-free evaluation package:

```bash
arka judge-demo init ./judge-demo
arka judge-demo check ./judge-demo
```

The package includes a manifest, synthetic-data policy, safe environment
example, and commands judges can run against an existing Arka installation.
It does not rebuild the project or contain production credentials.

Supported platforms are macOS 12+, Linux with glibc, and Windows through WSL2.
The generated README includes virtual-environment, activation, and `pip`
installation instructions for each platform.
