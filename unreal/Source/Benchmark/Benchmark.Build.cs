// Benchmark.Build.cs
// Lista os modulos da engine que o codigo do projeto usa.
// Mudancas em relacao ao original: "RenderCore" (tempos da thread de render) e os modulos
// de Blueprint dos plugins da NVIDIA (consulta de suporte e FPS do Frame Generation).

using UnrealBuildTool;

public class Benchmark : ModuleRules
{
	public Benchmark(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;

		PublicDependencyModuleNames.AddRange(new string[] { "Core", "CoreUObject", "Engine", "InputCore", "RHI", "RenderCore", "UMG" });

		PrivateDependencyModuleNames.AddRange(new string[] { "DLSSBlueprint", "StreamlineBlueprint", "StreamlineDLSSGBlueprint" });
	}
}