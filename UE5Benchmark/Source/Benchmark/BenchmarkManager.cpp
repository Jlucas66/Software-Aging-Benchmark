// BenchmarkManager.cpp
// Versao modificada para testes de estresse longos com DLSS.
// Veja o cabecalho (BenchmarkManager.h) para a lista de parametros de linha de comando.

#include "BenchmarkManager.h"
#include "Blueprint/UserWidget.h"
#include "Kismet/GameplayStatics.h"
#include "Kismet/KismetSystemLibrary.h"
#include "Engine/World.h"
#include "Engine/Engine.h"
#include "Engine/GameViewportClient.h"
#include "UnrealClient.h"
#include "HAL/IConsoleManager.h"
#include "HAL/PlatformMemory.h"
#include "HAL/PlatformTime.h"
#include "HAL/FileManager.h"
#include "Misc/App.h"
#include "Misc/CommandLine.h"
#include "Misc/Parse.h"
#include "Misc/Paths.h"
#include "Misc/FileHelper.h"
#include "Misc/DateTime.h"
#include "RHI.h"
#include "DynamicRHI.h"
#include "RenderCore.h"
#include "UObject/Class.h"

// Plugins da NVIDIA (DLSS 4.5 plugin 8.6.1 para UE 5.4)
#include "DLSSLibrary.h"             // modulo DLSSBlueprint
#include "StreamlineLibrary.h"       // modulo StreamlineBlueprint
#include "StreamlineLibraryDLSSG.h"  // modulo StreamlineDLSSGBlueprint

FTimerHandle DetailsTimer;

namespace
{
    // cvars que sempre aparecem no run_config.json, para auditoria de cada teste
    const TCHAR* GAuditCVars[] = {
        TEXT("r.NGX.Enable"),
        TEXT("r.NGX.DLSS.Enable"),
        TEXT("r.NGX.DLSS.DenoiserMode"),
        TEXT("r.NGX.DLSS.Preset"),
        TEXT("r.NGX.DLSSRR.Preset"),
        TEXT("r.Streamline.DLSSG.Enable"),
        TEXT("r.Streamline.DLSSG.FramesToGenerate"),
        TEXT("r.Shadow.Denoiser"),
        TEXT("r.Lumen.Reflections.ScreenSpaceReconstruction"),
        TEXT("r.Lumen.Reflections.Temporal"),
        TEXT("r.ScreenPercentage"),
        TEXT("r.AntiAliasingMethod"),
        TEXT("r.RayTracing"),
        TEXT("r.Lumen.HardwareRayTracing"),
        TEXT("r.VSync"),
        TEXT("t.MaxFPS"),
    };

    FString JsonEscape(const FString& In)
    {
        FString Out = In.Replace(TEXT("\\"), TEXT("\\\\"));
        Out = Out.Replace(TEXT("\""), TEXT("\\\""));
        return Out;
    }

    // Nome legivel de um valor de UENUM (ex.: UDLSSSupport::Supported -> "Supported")
    template <typename TEnum>
    FString EnumName(TEnum Value)
    {
        const UEnum* Enum = StaticEnum<TEnum>();
        return Enum ? Enum->GetNameStringByValue(static_cast<int64>(Value)) : FString::FromInt(static_cast<int32>(Value));
    }

    FString CVarValueOrMissing(const TCHAR* Name)
    {
        IConsoleVariable* CVar = IConsoleManager::Get().FindConsoleVariable(Name);
        return CVar ? CVar->GetString() : FString(TEXT("<missing>"));
    }
}

ABenchmarkManager::ABenchmarkManager()
{
    PrimaryActorTick.bCanEverTick = true;
    bBenchmarkComplete = false;
    CurrentFPS = 0.f;
    AverageFPS = 0.f;
    RendererName = "";
    GPUName = "";
    Resolution = "";
}

void ABenchmarkManager::BeginPlay()
{
    Super::BeginPlay();
    bBenchmarkComplete = false;
    FPSHistory.Empty();
    WindowFrameTimesMs.Reset();
    StartTimeSeconds = FPlatformTime::Seconds();

    GetWorld()->GetTimerManager().SetTimer(DetailsTimer, this, &ABenchmarkManager::GetRendererDetails, 0.2f, false);

    ReadCommandLine();

    IFileManager::Get().MakeDirectory(*OutDir, true);
    SamplesPath = FPaths::Combine(OutDir, TEXT("engine_samples.csv"));

    // Cabecalho so na primeira vez: se o jogo for reiniciado depois de um crash,
    // as novas linhas continuam no mesmo arquivo.
    if (!IFileManager::Get().FileExists(*SamplesPath))
    {
        AppendLine(SamplesPath,
            TEXT("timestamp_utc,elapsed_s,lap,frames,avg_fps,avg_frametime_ms,p99_frametime_ms,low1_fps,max_frametime_ms,gpu_time_ms,game_thread_ms,render_thread_ms,process_mem_mb,dlssg_fps,dlssg_frames_presented\n"));
    }

    ApplyRequestedCVars();

    // Espera alguns segundos para tudo inicializar e registra o estado real dos cvars.
    GetWorld()->GetTimerManager().SetTimer(RunConfigTimer, this, &ABenchmarkManager::WriteRunConfig, 3.0f, false);

    // Amostragem periodica (o fim do teste tambem e verificado aqui, pelo relogio de parede).
    GetWorld()->GetTimerManager().SetTimer(SampleTimer, this, &ABenchmarkManager::WriteSample, SampleIntervalSeconds, true);

    UE_LOG(LogTemp, Log, TEXT("[Bench] Iniciado: fase=%s duracao=%.0fs intervalo=%.1fs saida=%s"),
        *PhaseTag, TestDurationSeconds, SampleIntervalSeconds, *OutDir);
}

void ABenchmarkManager::EndPlay(const EEndPlayReason::Type EndPlayReason)
{
    // Grava o que estiver pendente (ex.: o jogo foi fechado pelo orquestrador).
    // Marca como concluido antes, para WriteSample nao tentar fechar o jogo de novo.
    bBenchmarkComplete = true;
    WriteSample();
    Super::EndPlay(EndPlayReason);
}

void ABenchmarkManager::ReadCommandLine()
{
    const TCHAR* Cmd = FCommandLine::Get();

    FParse::Value(Cmd, TEXT("BenchPhase="), PhaseTag);
    if (PhaseTag.IsEmpty())
    {
        PhaseTag = TEXT("editor");
    }

    float FloatValue = 0.f;
    if (FParse::Value(Cmd, TEXT("BenchDuration="), FloatValue) && FloatValue > 0.f)
    {
        TestDurationSeconds = FloatValue;
    }

    FloatValue = 0.f;
    if (FParse::Value(Cmd, TEXT("BenchInterval="), FloatValue) && FloatValue > 0.f)
    {
        SampleIntervalSeconds = FloatValue;
    }

    FParse::Value(Cmd, TEXT("BenchOutDir="), OutDir);
    if (OutDir.IsEmpty())
    {
        OutDir = FPaths::Combine(FPaths::ProjectSavedDir(), TEXT("BenchResults"), PhaseTag);
    }
    FPaths::NormalizeDirectoryName(OutDir);

    // false = nao parar em virgula; os pares sao separados por ';'
    FParse::Value(Cmd, TEXT("BenchCVars="), RequestedCVarsRaw, false);

    RequestedCVars.Reset();
    TArray<FString> Items;
    RequestedCVarsRaw.ParseIntoArray(Items, TEXT(";"), true);
    for (const FString& Item : Items)
    {
        FString Name, Value;
        if (Item.Split(TEXT("="), &Name, &Value))
        {
            Name.TrimStartAndEndInline();
            Value.TrimStartAndEndInline();
            if (!Name.IsEmpty())
            {
                RequestedCVars.Add(TPair<FString, FString>(Name, Value));
            }
        }
    }
}

void ABenchmarkManager::ApplyRequestedCVars()
{
    IConsoleManager& ConsoleManager = IConsoleManager::Get();

    for (const TPair<FString, FString>& Pair : RequestedCVars)
    {
        IConsoleVariable* CVar = ConsoleManager.FindConsoleVariable(*Pair.Key);
        if (!CVar)
        {
            UE_LOG(LogTemp, Warning, TEXT("[Bench] cvar nao existe (plugin desabilitado?): %s"), *Pair.Key);
            continue;
        }
        if (CVar->TestFlags(ECVF_ReadOnly))
        {
            UE_LOG(LogTemp, Warning, TEXT("[Bench] cvar e somente leitura em runtime, ignorada: %s (defina no DefaultEngine.ini)"), *Pair.Key);
            continue;
        }
        CVar->Set(*Pair.Value, ECVF_SetByConsole);
        UE_LOG(LogTemp, Log, TEXT("[Bench] cvar aplicada: %s=%s (atual: %s)"), *Pair.Key, *Pair.Value, *CVar->GetString());
    }
}

void ABenchmarkManager::WriteRunConfig()
{
    GetRendererDetails();

    FString Json = TEXT("{\n");
    Json += FString::Printf(TEXT("  \"phase\": \"%s\",\n"), *JsonEscape(PhaseTag));
    Json += FString::Printf(TEXT("  \"written_utc\": \"%s\",\n"), *FDateTime::UtcNow().ToIso8601());
    Json += FString::Printf(TEXT("  \"engine_version\": \"%s\",\n"), *JsonEscape(FEngineVersion::Current().ToString()));
    Json += FString::Printf(TEXT("  \"gpu\": \"%s\",\n"), *JsonEscape(GPUName));
    Json += FString::Printf(TEXT("  \"rhi\": \"%s\",\n"), *JsonEscape(RendererName));
    Json += FString::Printf(TEXT("  \"resolution\": \"%s\",\n"), *JsonEscape(Resolution));
    Json += FString::Printf(TEXT("  \"duration_s\": %.0f,\n"), TestDurationSeconds);
    Json += FString::Printf(TEXT("  \"interval_s\": %.2f,\n"), SampleIntervalSeconds);

    // Para cada cvar pedida: valor pedido x valor real depois de aplicar.
    Json += TEXT("  \"cvars\": [\n");
    for (int32 i = 0; i < RequestedCVars.Num(); ++i)
    {
        const TPair<FString, FString>& Pair = RequestedCVars[i];
        IConsoleVariable* CVar = IConsoleManager::Get().FindConsoleVariable(*Pair.Key);
        const bool bExists = CVar != nullptr;
        const bool bReadOnly = bExists && CVar->TestFlags(ECVF_ReadOnly);
        const FString Actual = bExists ? CVar->GetString() : FString(TEXT("<missing>"));

        Json += FString::Printf(
            TEXT("    {\"name\": \"%s\", \"requested\": \"%s\", \"actual\": \"%s\", \"exists\": %s, \"read_only\": %s}%s\n"),
            *JsonEscape(Pair.Key), *JsonEscape(Pair.Value), *JsonEscape(Actual),
            bExists ? TEXT("true") : TEXT("false"),
            bReadOnly ? TEXT("true") : TEXT("false"),
            (i < RequestedCVars.Num() - 1) ? TEXT(",") : TEXT(""));
    }
    Json += TEXT("  ],\n");

    // Suporte de hardware informado pelo proprio plugin da NVIDIA.
    // "Supported" = recurso disponivel nesta GPU/driver/SO. Qualquer outro valor diz o motivo.
    SupportDLSS = EnumName(UDLSSLibrary::QueryDLSSSupport());
    SupportRR = EnumName(UDLSSLibrary::QueryDLSSRRSupport());
    SupportDLSSG = EnumName(UStreamlineLibraryDLSSG::QueryDLSSGSupport());
    ActiveDLSSMode = EnumName(UDLSSLibrary::GetDLSSMode());
    ActiveDLSSGMode = EnumName(UStreamlineLibraryDLSSG::GetDLSSGMode());
    Json += TEXT("  \"support\": {\n");
    Json += FString::Printf(TEXT("    \"dlss_sr\": \"%s\",\n"), *SupportDLSS);
    Json += FString::Printf(TEXT("    \"dlss_rr\": \"%s\",\n"), *SupportRR);
    Json += FString::Printf(TEXT("    \"dlssg\": \"%s\",\n"), *SupportDLSSG);
    Json += FString::Printf(TEXT("    \"dlss_mode\": \"%s\",\n"), *ActiveDLSSMode);
    Json += FString::Printf(TEXT("    \"dlssg_mode\": \"%s\"\n"), *ActiveDLSSGMode);
    Json += TEXT("  },\n");
    UE_LOG(LogTemp, Log, TEXT("[Bench] Suporte: DLSS-SR=%s DLSS-RR=%s DLSS-FG=%s | modo DLSS=%s FG=%s"),
        *SupportDLSS, *SupportRR, *SupportDLSSG, *ActiveDLSSMode, *ActiveDLSSGMode);

    // Estado de todas as cvars relevantes para DLSS, pedidas ou nao.
    Json += TEXT("  \"audit\": {\n");
    const int32 NumAudit = UE_ARRAY_COUNT(GAuditCVars);
    for (int32 i = 0; i < NumAudit; ++i)
    {
        Json += FString::Printf(TEXT("    \"%s\": \"%s\"%s\n"),
            GAuditCVars[i], *JsonEscape(CVarValueOrMissing(GAuditCVars[i])),
            (i < NumAudit - 1) ? TEXT(",") : TEXT(""));
    }
    Json += TEXT("  }\n}\n");

    const FString Path = FPaths::Combine(OutDir, TEXT("run_config.json"));
    FFileHelper::SaveStringToFile(Json, *Path, FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM);
    UE_LOG(LogTemp, Log, TEXT("[Bench] run_config.json gravado em %s"), *Path);
}

void ABenchmarkManager::Tick(float DeltaTime)
{
    Super::Tick(DeltaTime);

    // FApp::GetDeltaTime() e o tempo real do frame (o DeltaTime do mundo e limitado
    // pela engine em travadas longas, o que esconderia picos).
    const float RawDelta = static_cast<float>(FApp::GetDeltaTime());
    if (RawDelta > 0.f)
    {
        CurrentFPS = 1.0f / RawDelta;
        if (!bBenchmarkComplete)
        {
            WindowFrameTimesMs.Add(RawDelta * 1000.0f);
        }
    }
}

FString ABenchmarkManager::GetDLSSStatusLine() const
{
    if (SupportDLSS.IsEmpty())
    {
        return TEXT("DLSS: verificando...");
    }
    FString Line = FString::Printf(TEXT("DLSS %s (SR %s, RR %s, FG %s) | FG %s"),
        *ActiveDLSSMode, *SupportDLSS, *SupportRR, *SupportDLSSG, *ActiveDLSSGMode);
    if (LastDLSSGFps > 0.f)
    {
        Line += FString::Printf(TEXT(" %.0f fps exibidos"), LastDLSSGFps);
    }
    return Line;
}

double ABenchmarkManager::GetElapsedSeconds() const
{
    return FPlatformTime::Seconds() - StartTimeSeconds;
}

void ABenchmarkManager::WriteSample()
{
    const int32 N = WindowFrameTimesMs.Num();
    if (N > 0 && !SamplesPath.IsEmpty())
    {
        double SumMs = 0.0;
        float MaxMs = 0.f;
        for (const float Ms : WindowFrameTimesMs)
        {
            SumMs += Ms;
            MaxMs = FMath::Max(MaxMs, Ms);
        }
        const double AvgMs = SumMs / N;

        TArray<float> Sorted = WindowFrameTimesMs;
        Sorted.Sort();
        const int32 P99Index = FMath::Clamp(FMath::CeilToInt(0.99f * static_cast<float>(N)) - 1, 0, N - 1);
        const float P99Ms = Sorted[P99Index];

        const double AvgFps = AvgMs > 0.0 ? 1000.0 / AvgMs : 0.0;
        const double Low1Fps = P99Ms > 0.f ? 1000.0 / P99Ms : 0.0;

        // Tempos medidos pela propria engine (podem vir 0 em algumas configuracoes).
        const float GpuMs = FPlatformTime::ToMilliseconds(RHIGetGPUFrameCycles(0));
        const float GameMs = FPlatformTime::ToMilliseconds(GGameThreadTime);
        const float RenderMs = FPlatformTime::ToMilliseconds(GRenderThreadTime);

        const FPlatformMemoryStats MemStats = FPlatformMemory::GetStats();
        const double MemMb = static_cast<double>(MemStats.UsedPhysical) / (1024.0 * 1024.0);

        // Com Frame Generation ligado, a engine so ve os frames renderizados; o plugin
        // informa a taxa de frames realmente exibidos (0 quando o FG esta desligado).
        float DLSSGFps = 0.f;
        int32 DLSSGFramesPresented = 0;
        UStreamlineLibraryDLSSG::GetDLSSGFrameTiming(DLSSGFps, DLSSGFramesPresented);
        LastDLSSGFps = DLSSGFps;

        const FString Line = FString::Printf(
            TEXT("%s,%.1f,%d,%d,%.2f,%.3f,%.3f,%.2f,%.3f,%.3f,%.3f,%.3f,%.1f,%.2f,%d\n"),
            *FDateTime::UtcNow().ToIso8601(), GetElapsedSeconds(), CurrentLap, N,
            AvgFps, AvgMs, P99Ms, Low1Fps, MaxMs, GpuMs, GameMs, RenderMs, MemMb,
            DLSSGFps, DLSSGFramesPresented);

        AppendLine(SamplesPath, Line);
        WindowFrameTimesMs.Reset();
    }

    if (!bBenchmarkComplete && GetElapsedSeconds() >= TestDurationSeconds)
    {
        OnTestDurationElapsed();
    }
}

void ABenchmarkManager::OnTestDurationElapsed()
{
    bBenchmarkComplete = true;
    UE_LOG(LogTemp, Log, TEXT("[Bench] Duracao atingida (%.0fs) - fase %s concluida"), TestDurationSeconds, *PhaseTag);

    if (bQuitOnComplete)
    {
        // No Editor isso encerra o Play; no jogo empacotado fecha o executavel.
        UKismetSystemLibrary::QuitGame(GetWorld(), nullptr, EQuitPreference::Quit, false);
    }
}

void ABenchmarkManager::OnLapComplete(int32 LapNumber)
{
    CurrentLap = LapNumber;
    UE_LOG(LogTemp, Log, TEXT("[Bench] Volta %d completa (fase %s, %.0fs)"), LapNumber, *PhaseTag, GetElapsedSeconds());
}

void ABenchmarkManager::AppendLine(const FString& FilePath, const FString& Line) const
{
    FFileHelper::SaveStringToFile(
        Line, *FilePath,
        FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM,
        &IFileManager::Get(),
        FILEWRITE_Append);
}

// ---------------------------------------------------------------------------
// Funcoes originais do projeto, mantidas (nao sao usadas no modo continuo).
// ---------------------------------------------------------------------------

void ABenchmarkManager::CalculateAvgFPS()
{
    AverageFPS = 0.0f;
    if (FPSHistory.Num() == 0)
    {
        return;
    }
    float Sum = 0.0f;
    for (const float Fps : FPSHistory)
    {
        Sum += Fps;
    }
    AverageFPS = Sum / FPSHistory.Num();
}

void ABenchmarkManager::SaveResultsToDisk()
{
    FString SaveData = "Time,FPS\n";
    for (int32 i = 0; i < FPSHistory.Num(); ++i)
    {
        SaveData += FString::Printf(TEXT("%d,%.2f\n"), i, FPSHistory[i]);
    }

    FString SaveDataAvgFPS = FString::Printf(TEXT("%.2f\n"), AverageFPS);
    SaveDataAvgFPS += FString::Printf(TEXT("%s - %s - %s"), *GPUName, *RendererName, *Resolution);

    FString ProjectDir = FPaths::ProjectDir();
    FString ParentDir = FPaths::GetPath(ProjectDir.LeftChop(1));
    FFileHelper::SaveStringToFile(SaveData, *(ParentDir + "/BenchmarkResultsPerFrame.csv"));
    FFileHelper::SaveStringToFile(SaveDataAvgFPS, *(ParentDir + "/BenchmarkResults.txt"));
}

void ABenchmarkManager::OnBenchmarkComplete()
{
    bBenchmarkComplete = true;
    CalculateAvgFPS();
    SaveResultsToDisk();

    APlayerController* PlayerController = UGameplayStatics::GetPlayerController(GetWorld(), 0);
    if (PlayerController && PlayerController->PlayerCameraManager)
    {
        PlayerController->bShowMouseCursor = true;
        FInputModeUIOnly InputMode;
        PlayerController->SetInputMode(InputMode);
        PlayerController->PlayerCameraManager->StartCameraFade(0.0f, 1.0f, 1.0f, FLinearColor::Black, false, true);
    }

    DisplayEndScreenUI();
}

void ABenchmarkManager::DisplayEndScreenUI()
{
    if (EndScreenWidgetClass)
    {
        UUserWidget* EndScreen = CreateWidget<UUserWidget>(GetWorld(), EndScreenWidgetClass);
        if (EndScreen)
        {
            EndScreen->AddToViewport();
        }
    }
}

void ABenchmarkManager::GetRendererDetails()
{
    if (GRHIAdapterName.IsEmpty())
    {
        UE_LOG(LogTemp, Warning, TEXT("No GPU adapter name available."));
        return;
    }

    GPUName = GRHIAdapterName;
    if (GDynamicRHI)
    {
        RendererName = GDynamicRHI->GetName();
    }
    if (GEngine && GEngine->GameViewport && GEngine->GameViewport->Viewport)
    {
        const FIntPoint Size = GEngine->GameViewport->Viewport->GetSizeXY();
        Resolution = FString::Printf(TEXT("%dx%d"), Size.X, Size.Y);
    }
}

FString ABenchmarkManager::GetBenchmarkSettings()
{
    return FString::Printf(TEXT("%s - %s - %s"), *GPUName, *RendererName, *Resolution);
}