# Public signing for Kairos Studio

No signing identity is configured yet. Local packages show `publicReleaseReady: false` in `signing-report.json`
and must not be presented as signed.

## Certificate in the Windows store

Get a code-signing identity from a recognized authority and install the certificate and its private key provider
following their instructions. Never store PFX files or passwords in the repository. With SignTool from the
Windows SDK:

```powershell
./desktop/publish.ps1 -RequireSignature -CertificateThumbprint '40_CHARACTER_THUMBPRINT'
```

The thumbprint identifies the certificate; it isn't a password. The script looks in CurrentUser first and then in
LocalMachine, checks validity and code-signing usage, applies SHA-256 and an RFC 3161 timestamp, and verifies the
result.

## Microsoft Artifact Signing

Set up an account, identity validation, a **Public Trust** profile and signing permissions in Azure. Install the
Artifact Signing Client Tools and sign in with the Azure CLI. Copy `signing-metadata.example.json` to
`signing-metadata.json` outside the package and fill in Endpoint, CodeSigningAccountName and
CertificateProfileName. The example prefers the Azure CLI; adjust the credential selection if you use another
identity.

```powershell
./desktop/publish.ps1 -RequireSignature `
  -SigningMetadata 'C:\Signing\signing-metadata.json' `
  -SigningDlib 'C:\Signing\Azure.CodeSigning.Dlib.dll' `
  -SignTool 'C:\Signing\signtool.exe'
```

Follow the [official instructions](https://learn.microsoft.com/azure/trusted-signing/how-to-signing-integrations)
for compatible SignTool and dlib versions. Only HTTPS endpoints on `codesigning.azure.net` are accepted. The app
never creates Azure resources or triggers paid signing on its own.

## Checking the result

`signing-report.json` must show `publicReleaseReady: true`, `Valid` signatures, the expected publisher and
`timestamped: true` for both binaries. Check `SHA256SUMS.txt`, keep the published package and scan the folder with
Defender before distributing it.

A consistent identity helps build reputation. According to
[Microsoft](https://learn.microsoft.com/windows/apps/package-and-deploy/smartscreen-reputation), EV certificates no
longer give an automatic SmartScreen exemption either. The Microsoft Store is another distribution option, with
managed signing after certification.

To include the installer and the ZIP as well, run `release.ps1` from the root with the same arguments. Inno Setup
calls the signer during compilation to sign the uninstaller and its internal copies, as well as the final
installer. `-RequireSignature` prevents finishing a release without a configured identity.
