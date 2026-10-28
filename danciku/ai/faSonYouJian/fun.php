<?php
// use 放到函数外面（全局位置）
require 'PHPMailer.php';
require 'SMTP.php';
require 'Exception.php';

use PHPMailer\PHPMailer\PHPMailer;
use PHPMailer\PHPMailer\SMTP;
use PHPMailer\PHPMailer\Exception;

/**
 * 发送邮件函数
 * @param string $po_strBiaoTi 邮件标题
 * @param string $po_strNeiRon 邮件内容
 * @return void
 */
function FaYouJian
  (
  $po_strBiaoTi, # 邮件标题
  $po_strNeiRon  # 邮件内容
  )
{
    $mail = new PHPMailer(true);
    try {
        $mail->CharSet = 'UTF-8';
        $mail->isSMTP();
        $mail->Host = 'smtp.qq.com';
        $mail->SMTPAuth = true;
        $mail->Username = 'sheng901112@qq.com';
        $mail->Password = 'ddgxeutvrumybihe';
        $mail->SMTPSecure = 'ssl';
        $mail->Port = 465;

        $mail->setFrom('sheng901112@qq.com', '');
        $mail->addAddress('415107996@qq.com');

        $mail->isHTML(true);
        $mail->Subject = $po_strBiaoTi;
        $mail->Body    = $po_strNeiRon;

        $mail->send();
        echo "发送成功\n";
    } catch (Exception $e) {
        echo "失败：" . $mail->ErrorInfo . "\n";
    }
}

// ===== 调用示例 =====
// FaYouJian('自定义标题', '自定义邮件内容');
?>