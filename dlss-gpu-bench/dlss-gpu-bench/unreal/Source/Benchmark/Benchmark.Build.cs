// Benchmark.Build.cs
// Lista os modulos da engine que o codigo do projeto usa.
// Mudanca em relacao ao original: adicionado "RenderCore" (tempos de thread de render).

using UnrealBuildTool;

public class Benchmark : ModuleRules
{
	public Benchmark(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;

		PublicDependencyModuleNames.AddRange(new string[] { "Core", "CoreUObject", "Engine", "InputCore", "RHI", "RenderCore", "UMG" });

		PrivateDependencyModuleNames.AddRange(new string[] { });
	}
}
