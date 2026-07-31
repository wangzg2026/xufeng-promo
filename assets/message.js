(function () {
  // 留言提交到生产后端（另一个域名），后端只对本站来源放行 CORS。
  var API_BASE = "https://fapiao.chinavtax.com";
  var TAXPAYER_RE = /^[0-9A-Z]{15,20}$/;
  var EMAIL_RE = /^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$/;

  var captchaId = "";

  function $(id) {
    return document.getElementById(id);
  }

  function setError(field, message) {
    var node = $(field);
    if (node) {
      node.textContent = message || "";
    }
    return !message;
  }

  function clearErrors() {
    ["inquiryTaxpayerError", "inquiryEmailError", "inquiryContentError", "inquiryCaptchaError"].forEach(
      function (id) {
        setError(id, "");
      }
    );
    $("inquiryStatus").textContent = "";
  }

  async function loadCaptcha() {
    var image = $("inquiryCaptchaImage");
    try {
      var response = await fetch(API_BASE + "/api/captcha", { method: "GET" });
      if (!response.ok) {
        throw new Error("captcha unavailable");
      }
      var body = await response.json();
      captchaId = body.captchaId;
      image.src = body.imageDataUri;
      image.alt = "图形验证码，点击可刷新";
    } catch (error) {
      captchaId = "";
      image.removeAttribute("src");
      image.alt = "验证码加载失败，点击重试";
      $("inquiryStatus").textContent = "验证码加载失败，请检查网络后点击验证码重试。";
    }
  }

  function validate(values) {
    var ok = true;
    ok = setError("inquiryTaxpayerError", TAXPAYER_RE.test(values.taxpayerNum) ? "" : "请填写 15-20 位的统一社会信用代码（字母请大写）") && ok;
    ok = setError("inquiryEmailError", EMAIL_RE.test(values.email) ? "" : "请填写正确的邮箱地址") && ok;
    ok = setError("inquiryContentError", values.content ? "" : "请填写留言内容") && ok;
    ok = setError("inquiryCaptchaError", values.captchaAnswer ? "" : "请填写图形验证码") && ok;
    return ok;
  }

  function readValues() {
    return {
      category: $("inquiryCategory").value,
      taxpayerNum: $("inquiryTaxpayer").value.trim().toUpperCase(),
      email: $("inquiryEmail").value.trim(),
      content: $("inquiryContent").value.trim(),
      captchaAnswer: $("inquiryCaptcha").value.trim(),
    };
  }

  async function submitInquiry(event) {
    event.preventDefault();
    clearErrors();

    var values = readValues();
    if (!validate(values)) {
      return;
    }
    if (!captchaId) {
      $("inquiryStatus").textContent = "验证码未加载，请点击验证码图片后重试。";
      return;
    }

    var button = $("inquirySubmit");
    button.disabled = true;
    button.textContent = "提交中…";

    try {
      var response = await fetch(API_BASE + "/api/public/inquiries", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          category: values.category,
          taxpayerNum: values.taxpayerNum,
          email: values.email,
          content: values.content,
          captchaId: captchaId,
          captchaAnswer: values.captchaAnswer,
        }),
      });

      if (response.status === 201) {
        var body = await response.json();
        $("inquiryTicketId").textContent = body.inquiryId;
        $("inquiryForm").classList.add("hidden");
        $("inquirySuccess").classList.remove("hidden");
        return;
      }

      var detail = "";
      try {
        var errorBody = await response.json();
        detail = typeof errorBody.detail === "string" ? errorBody.detail : "";
      } catch (parseError) {
        detail = "";
      }

      if (response.status === 429) {
        $("inquiryStatus").textContent = detail || "提交过于频繁，请稍后再试。";
      } else if (response.status === 400) {
        setError("inquiryCaptchaError", detail || "图形验证码不正确");
      } else {
        $("inquiryStatus").textContent = detail || "提交失败，请稍后重试。";
      }
      await loadCaptcha();
      $("inquiryCaptcha").value = "";
    } catch (error) {
      $("inquiryStatus").textContent = "网络异常，提交失败，请稍后重试。";
    } finally {
      button.disabled = false;
      button.textContent = "提交留言";
    }
  }

  window.addEventListener("DOMContentLoaded", function () {
    loadCaptcha();
    $("inquiryForm").addEventListener("submit", submitInquiry);
    $("inquiryCaptchaRefresh").addEventListener("click", function () {
      $("inquiryCaptcha").value = "";
      loadCaptcha();
    });
    $("inquiryContent").addEventListener("input", function (event) {
      $("inquiryCount").textContent = String(event.target.value.length);
    });
    $("inquiryAgain").addEventListener("click", function () {
      $("inquiryForm").reset();
      $("inquiryCount").textContent = "0";
      clearErrors();
      $("inquirySuccess").classList.add("hidden");
      $("inquiryForm").classList.remove("hidden");
      loadCaptcha();
    });
  });
})();
