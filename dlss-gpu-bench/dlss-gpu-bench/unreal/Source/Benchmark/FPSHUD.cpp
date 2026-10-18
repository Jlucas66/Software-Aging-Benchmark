// FPSHUD.cpp
// Versao modificada: alem do FPS e da GPU, mostra o nome do teste, o tempo
// decorrido e a volta atual, para conferir de longe que o teste esta rodando.

#include "FPSHUD.h"
#include "Kismet/GameplayStatics.h"
#include "Engine/Canvas.h"
#include "Engine/Font.h"
#include "UObject/ConstructorHelpers.h"

void AFPSHUD::BeginPlay()
{
    Super::BeginPlay();
    BenchmarkManagerRef = Cast<ABenchmarkManager>(UGameplayStatics::GetActorOfClass(GetWorld(), ABenchmarkManager::StaticClass()));
}

void AFPSHUD::DrawHUD()
{
    Super::DrawHUD();

    if (!BenchmarkManagerRef)
    {
        return;
    }

    UFont* CustomFont = LoadObject<UFont>(nullptr, TEXT("/Game/Benchmark/Font/RubikWetPaint-Regular_Font.RubikWetPaint-Regular_Font"));
    UFont* CustomFontSmall = LoadObject<UFont>(nullptr, TEXT("/Game/Benchmark/Font/RubikWetPaint-Regular_Font_sm.RubikWetPaint-Regular_Font_sm"));

    const int32 Elapsed = static_cast<int32>(BenchmarkManagerRef->GetElapsedSeconds());
    const int32 Hours = Elapsed / 3600;
    const int32 Minutes = (Elapsed % 3600) / 60;
    const int32 Seconds = Elapsed % 60;

    const FString Line1 = FString::Printf(TEXT("FPS: %.2f"), BenchmarkManagerRef->CurrentFPS);
    const FString Line2 = BenchmarkManagerRef->GetBenchmarkSettings();
    const FString Line3 = FString::Printf(TEXT("%s | %02d:%02d:%02d | volta %d"),
        *BenchmarkManagerRef->GetPhaseTag(), Hours, Minutes, Seconds, BenchmarkManagerRef->GetCurrentLap());

    const FLinearColor Line1Color(1.0f, 0.2f, 0.2f, 0.9f);
    const FLinearColor Line2Color(0.2f, 0.2f, 1.0f, 0.9f);
    const FLinearColor Line3Color(1.0f, 1.0f, 1.0f, 0.9f);
    const FVector2D ShadowOffset(2.0f, 2.0f);
    const FLinearColor ShadowColor(0, 0, 0, 0.6f);

    UFont* Large = CustomFont ? CustomFont : GEngine->GetLargeFont();
    UFont* Small = CustomFontSmall ? CustomFontSmall : GEngine->GetLargeFont();

    FCanvasTextItem Item1(FVector2D(50, 50), FText::FromString(Line1), Large, Line1Color);
    Item1.EnableShadow(ShadowColor, ShadowOffset);
    Canvas->DrawItem(Item1);

    FCanvasTextItem Item2(FVector2D(50, 150), FText::FromString(Line2), Small, Line2Color);
    Item2.EnableShadow(ShadowColor, ShadowOffset);
    Canvas->DrawItem(Item2);

    FCanvasTextItem Item3(FVector2D(50, 210), FText::FromString(Line3), Small, Line3Color);
    Item3.EnableShadow(ShadowColor, ShadowOffset);
    Canvas->DrawItem(Item3);
}
