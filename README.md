# Python sound optimizer project

<table align="center">
  <tr>
    <td align="center">
        <a href="https://github.com/DariuszMak/sound-optimizer/releases/download/1.0.0/Sound_optimizer.exe">
        <img src="images/drawings/Flow.png" alt="Flow" width="600">
      </a>
    </td>
  </tr>
</table>

### Project structure diagrams

##### Modular perspective

<p align="center">
  <img src="images/structure_module_pylib.svg" alt="Modular perspective" width="600">
</p>

##### Library dependencies perspective

<p align="center">
  <img src="images/structure_module_clustered.svg" alt="Library dependencies perspective" width="600">
</p>

## Requirements

- [UV](https://github.com/astral-sh/uv) package manager
- [Task](https://taskfile.dev/docs/installation) runner
- [Ffmpeg](https://github.com/BtbN/FFmpeg-Builds/releases)

### Fast Windows dev

```commandline
task full-dev-native ; 
```

### Generate diagrams

```commandline
task generate-diagrams ; 
```
