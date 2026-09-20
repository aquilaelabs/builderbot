# A BuilderBot node on Hyper-V. Run in an elevated PowerShell on the host.
#
# Rendered by the dashboard's Create sandbox VM (vmtemplate.py). Generation 2
# is UEFI, and its Secure Boot template rejects most Linux installers unless
# it is turned off or set to the Microsoft UEFI authority. Off is the one
# that works for every distribution the provisioner supports.
#
# The MAC is in Hyper-V's own range (00:15:5D:xx:xx:xx) and written without
# separators, which is the format Set-VMNetworkAdapter takes.
$ErrorActionPreference = 'Stop'

$Name   = '${name}'
$Root   = 'C:\VMs\${name}'
$Vhd    = "$Root\${name}.vhdx"
$Iso    = '${iso_path}'
$Switch = 'Default Switch'      # the network the node reaches the controller on

New-Item -ItemType Directory -Force -Path $Root | Out-Null
New-VM -Name $Name -Generation 2 -MemoryStartupBytes ${memory_gb}GB `
       -NewVHDPath $Vhd -NewVHDSizeBytes ${disk_gb}GB -SwitchName $Switch
Set-VM -Name $Name -ProcessorCount ${cores} -AutomaticCheckpointsEnabled $false `
       -CheckpointType Disabled -StaticMemory
Set-VMFirmware -VMName $Name -EnableSecureBoot Off
Add-VMDvdDrive -VMName $Name -Path $Iso
Set-VMFirmware -VMName $Name -FirstBootDevice (Get-VMDvdDrive -VMName $Name)
Set-VMNetworkAdapter -VMName $Name -StaticMacAddress '${mac_plain}'
Start-VM -Name $Name
