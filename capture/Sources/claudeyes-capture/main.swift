// claudeyes capture shim.
//
// One JSON line per frame on stdout. Nothing else. The Python side does the
// thinking; this exists because ScreenCaptureKit's runloop, async delegate and
// IOSurface lifetime semantics are exactly the parts a Python binding models
// worst, and because SCK hands us two things for free that we would otherwise
// pay for: a `.complete` vs `.idle` status flag, and per-frame dirtyRects.
//
// Hard rules from Apple that shape this file:
//   * frame processing must finish within minimumFrameInterval
//   * the surface must be released within interval * (queueDepth - 1)
// so the delegate does nothing but read attachments and print. No pixels are
// touched, no image is ever decoded.

import AVFoundation
import CoreGraphics
import Foundation
import ScreenCaptureKit

// MARK: - window ownership

/// Maps a screen rect to the app that owns the frontmost window under it.
/// Ownership beats geometry for attribution: change inside an app you never
/// touched is not something your click explains, however close it landed.
final class WindowIndex {
    private var entries: [(rect: CGRect, owner: String)] = []
    private var lastRefresh: CFAbsoluteTime = 0

    func refreshIfStale(_ maxAge: CFAbsoluteTime = 0.5) {
        let now = CFAbsoluteTimeGetCurrent()
        guard now - lastRefresh > maxAge else { return }
        lastRefresh = now
        guard let list = CGWindowListCopyWindowInfo(
            [.optionOnScreenOnly, .excludeDesktopElements], kCGNullWindowID
        ) as? [[String: Any]] else { return }
        // CGWindowList is front-to-back, which is the order we want.
        entries = list.compactMap { info in
            guard let owner = info[kCGWindowOwnerName as String] as? String,
                  let b = info[kCGWindowBounds as String] as? [String: Any],
                  let rect = CGRect(dictionaryRepresentation: b as CFDictionary)
            else { return nil }
            return (rect, owner)
        }
    }

    func owner(of rect: CGRect) -> String? {
        let p = CGPoint(x: rect.midX, y: rect.midY)
        for e in entries where e.rect.contains(p) { return e.owner }
        return nil
    }
}

// MARK: - output

final class Emitter {
    private let index = WindowIndex()
    private var frame: Int = 0
    private let out = FileHandle.standardOutput

    func hello(width: Int, height: Int, scale: Double) {
        write(["type": "hello", "width": width, "height": height,
               "scale": scale, "t": Date().timeIntervalSince1970])
    }

    func emit(dirty: [CGRect], t: Double) {
        guard !dirty.isEmpty else { return }
        index.refreshIfStale()
        frame += 1
        let rects: [[String: Any]] = dirty.map { r in
            var d: [String: Any] = ["x": Int(r.origin.x), "y": Int(r.origin.y),
                                    "w": Int(r.width), "h": Int(r.height)]
            if let o = index.owner(of: r) { d["app"] = o }
            return d
        }
        write(["t": t, "frame": frame, "dirty": rects])
    }

    private func write(_ obj: [String: Any]) {
        guard let data = try? JSONSerialization.data(withJSONObject: obj),
              var line = String(data: data, encoding: .utf8) else { return }
        line += "\n"
        out.write(Data(line.utf8))
    }
}

// MARK: - stream

final class Capture: NSObject, SCStreamOutput, SCStreamDelegate {
    private var stream: SCStream?
    private let emitter = Emitter()
    private let queue = DispatchQueue(label: "claudeyes.capture", qos: .userInitiated)
    private let fps: Double

    init(fps: Double) { self.fps = fps }

    func start() async throws {
        let content = try await SCShareableContent.excludingDesktopWindows(
            false, onScreenWindowsOnly: true)
        guard let display = content.displays.first else {
            FileHandle.standardError.write(Data("claudeyes: no display\n".utf8))
            exit(1)
        }

        // Filter by *including* every app rather than excluding an empty array:
        // `init(display:excludingWindows: [])` is a known SCK trap that leaves
        // the stream alive but never firing a callback.
        let filter = SCContentFilter(display: display,
                                     including: content.applications,
                                     exceptingWindows: [])

        let cfg = SCStreamConfiguration()
        cfg.width = display.width
        cfg.height = display.height
        cfg.minimumFrameInterval = CMTime(value: 1, timescale: CMTimeScale(fps))
        cfg.queueDepth = 5
        cfg.showsCursor = true
        cfg.pixelFormat = kCVPixelFormatType_32BGRA
        // We never read pixels, so keep the smallest buffers SCK will give us.
        cfg.scalesToFit = true

        emitter.hello(width: display.width, height: display.height, scale: 1.0)

        let s = SCStream(filter: filter, configuration: cfg, delegate: self)
        try s.addStreamOutput(self, type: .screen, sampleHandlerQueue: queue)
        try await s.startCapture()
        stream = s
    }

    func stream(_ stream: SCStream, didOutputSampleBuffer sb: CMSampleBuffer,
                of type: SCStreamOutputType) {
        guard type == .screen, CMSampleBufferIsValid(sb) else { return }
        guard let arr = CMSampleBufferGetSampleAttachmentsArray(sb, createIfNecessary: false)
                as? [[SCStreamFrameInfo: Any]],
              let info = arr.first else { return }

        // SCK already tells us nothing happened. Believe it; this is the free
        // always-on layer that makes a software perceptual hash unnecessary.
        if let raw = info[.status] as? Int,
           let status = SCFrameStatus(rawValue: raw), status != .complete { return }

        guard let dicts = info[.dirtyRects] as? [[String: Any]] else { return }
        let rects = dicts.compactMap { CGRect(dictionaryRepresentation: $0 as CFDictionary) }
        let t = CMSampleBufferGetPresentationTimeStamp(sb).seconds
        emitter.emit(dirty: rects, t: t > 0 ? Date().timeIntervalSince1970 : Date().timeIntervalSince1970)
    }

    // Streams die on sleep/wake with -3821. That is routine, not exceptional.
    func stream(_ stream: SCStream, didStopWithError error: Error) {
        FileHandle.standardError.write(Data("claudeyes: stream stopped (\(error)); restarting\n".utf8))
        self.stream = nil
        Task {
            try? await Task.sleep(nanoseconds: 1_000_000_000)
            try? await self.start()
        }
    }
}

// MARK: - main

let fps = ProcessInfo.processInfo.environment["CLAUDEYES_FPS"].flatMap(Double.init) ?? 4.0
let capture = Capture(fps: fps)

Task {
    do {
        try await capture.start()
    } catch {
        FileHandle.standardError.write(Data("""
        claudeyes: could not start capture: \(error)
        If SCShareableContent returned nothing, this is Screen Recording permission.
        System Settings > Privacy & Security > Screen Recording. SCK fails silently there.
        """.utf8))
        exit(1)
    }
}
RunLoop.main.run()
