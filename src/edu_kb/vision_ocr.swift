// OCR des guides scannés avec le framework Vision de macOS, et vérification de mots français.
//
//   vision_ocr ocr image.png [image.png ...]
//       une ligne JSON par image : {"image": …, "lines": [{"text", "conf", "x0", "y0", "x1", "y1"}]}
//       coordonnées normalisées (0 à 1), origine en haut à gauche
//   vision_ocr mots < mots.txt
//       pour chaque mot lu sur l'entrée (un par ligne), « 1 » s'il est français, « 0 » sinon
//
// Compilé à la première utilisation par edu_kb.ocr_vision (swiftc, outils en ligne de commande Xcode).
import AppKit
import Foundation
import Vision

func ocr(_ paths: ArraySlice<String>) throws {
    for path in paths {
        guard let image = NSImage(contentsOfFile: path),
              let cg = image.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
            FileHandle.standardError.write("image illisible : \(path)\n".data(using: .utf8)!)
            exit(1)
        }
        let request = VNRecognizeTextRequest()
        request.recognitionLevel = .accurate
        request.recognitionLanguages = ["fr-FR"]
        request.usesLanguageCorrection = true
        try VNImageRequestHandler(cgImage: cg, options: [:]).perform([request])
        var lines: [[String: Any]] = []
        for obs in request.results ?? [] {
            guard let top = obs.topCandidates(1).first else { continue }
            let b = obs.boundingBox
            lines.append(["text": top.string, "conf": top.confidence,
                          "x0": b.minX, "y0": 1 - b.maxY, "x1": b.maxX, "y1": 1 - b.minY])
        }
        let data = try JSONSerialization.data(withJSONObject: ["image": path, "lines": lines], options: [])
        print(String(data: data, encoding: .utf8)!)
    }
}

func words() {
    let checker = NSSpellChecker.shared
    while let word = readLine() {
        let miss = checker.checkSpelling(of: word, startingAt: 0, language: "fr", wrap: false,
                                         inSpellDocumentWithTag: 0, wordCount: nil)
        print(miss.location == NSNotFound ? "1" : "0")
    }
}

let args = CommandLine.arguments
switch args.count > 1 ? args[1] : "" {
case "ocr": try ocr(args.dropFirst(2))
case "mots": words()
default:
    FileHandle.standardError.write("usage : vision_ocr ocr image.png… | vision_ocr mots < mots.txt\n".data(using: .utf8)!)
    exit(2)
}
